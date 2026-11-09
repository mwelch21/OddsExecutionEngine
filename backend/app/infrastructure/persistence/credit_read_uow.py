"""Read side of the Credits tab (#104). DB-only: no write, no credits spent.

Burn is summed in SQL over quota observations, one row per upstream call, so a call
that coalesced refreshes shared is counted once. Hourly bucketing happens in the
engine, which keeps the read portable between Postgres and the SQLite smoke path.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.domain.credits import BurnRow, RemainingReading
from backend.app.domain.quota import UpstreamCallKind
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import quota_observations_table

observations = quota_observations_table.c


class SqlAlchemyCreditReadUnitOfWork:
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> "SqlAlchemyCreditReadUnitOfWork":
        self._session = self._session_factory.create_session()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        session = self._require_session()
        # Nothing here writes; only the read transaction to release.
        session.rollback()
        session.close()
        self._session = None

    def list_remaining(self, since: datetime) -> list[RemainingReading]:
        rows = self._require_session().execute(
            select(observations.observed_at, observations.remaining)
            .where(observations.observed_at >= since, observations.remaining.is_not(None))
            # Rows are written under a lock, so id order is observation order.
            .order_by(observations.id)
        )
        return [
            RemainingReading(observed_at=_utc(observed_at), remaining=remaining)
            for observed_at, remaining in rows
        ]

    def sum_burn(self, starts_at: datetime, ends_at: datetime) -> list[BurnRow]:
        rows = self._require_session().execute(
            select(
                observations.sport_key,
                observations.call_kind,
                func.coalesce(func.sum(observations.credits_spent), 0),
                func.count(),
            )
            .where(
                observations.observed_at >= starts_at,
                observations.observed_at < ends_at,
                # Calls from before kind was kept cannot be attributed; not counted.
                observations.call_kind.is_not(None),
            )
            .group_by(observations.sport_key, observations.call_kind)
        )
        return [
            BurnRow(
                sport_key=sport_key,
                kind=UpstreamCallKind(kind),
                credits=int(credits),
                calls=int(calls),
            )
            for sport_key, kind, credits, calls in rows
        ]

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Credit read unit of work must be entered before use.")
        return self._session


def _utc(value: datetime) -> datetime:
    # SQLite hands timestamps back naive; they were written as UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)
