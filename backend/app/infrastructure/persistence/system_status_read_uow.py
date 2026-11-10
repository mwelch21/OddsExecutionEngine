"""Read side of component status and operational metrics (#106).

Every read is DB-only and costs no credits. The probes (`SELECT 1` and the
notifier's listener connection) report a failure as a value, so one signal that
cannot be read never hides the others.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.domain.deliveries import DeliveryStatus
from backend.app.domain.quota import QuotaObservation, QuotaSource, UpstreamCallOutcome
from backend.app.domain.refresh_records import RefreshOutcomeStatus, RefreshScope
from backend.app.domain.system_status import (
    LastSuccessfulRefresh,
    PendingDeliveries,
    ProviderAnswer,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    auto_refresh_settings_table,
    deliveries_table,
    quota_observations_table,
    refresh_records_table,
)

# Set by the Go notifier on its LISTEN connection only (services/notifier store.Listen).
NOTIFIER_LISTENER_APPLICATION_NAME = "notifier-listener"


class SqlAlchemySystemStatusReadUnitOfWork:
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> "SqlAlchemySystemStatusReadUnitOfWork":
        self._session = self._session_factory.create_session()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        session = self._require_session()
        # Read only: release the read transaction. The database may be the thing
        # that is down, so releasing must not raise over the answer.
        try:
            session.rollback()
        except SQLAlchemyError:
            pass
        session.close()
        self._session = None

    def database_reachable(self) -> bool:
        try:
            self._require_session().execute(text("SELECT 1")).scalar_one()
        except SQLAlchemyError:
            self._reset()
            return False
        return True

    def notifier_listener_count(self) -> int | None:
        try:
            count = (
                self._require_session()
                .execute(
                    # This database only: a notifier listening on another one proves nothing.
                    text(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE application_name = :name AND datname = current_database()"
                    ),
                    {"name": NOTIFIER_LISTENER_APPLICATION_NAME},
                )
                .scalar_one()
            )
        except SQLAlchemyError:
            # No pg_stat_activity (SQLite) or no right to read it: the signal is unknown.
            self._reset()
            return None
        return int(count)

    def newest_provider_answer(self) -> ProviderAnswer | None:
        # The newest upstream call, balance checks included, ordered by when the
        # call was made rather than when its refresh finished (#121).
        row = (
            self._require_session()
            .execute(
                select(
                    quota_observations_table.c.call_outcome,
                    quota_observations_table.c.observed_at,
                )
                .order_by(
                    quota_observations_table.c.observed_at.desc(),
                    quota_observations_table.c.id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return ProviderAnswer(
            outcome=None
            if row["call_outcome"] is None
            else UpstreamCallOutcome(row["call_outcome"]),
            observed_at=_as_utc(row["observed_at"]),
        )

    def last_successful_refresh(self) -> LastSuccessfulRefresh | None:
        row = (
            self._require_session()
            .execute(
                select(
                    refresh_records_table.c.scope,
                    refresh_records_table.c.sport_key,
                    refresh_records_table.c.event_id,
                    refresh_records_table.c.finished_at,
                )
                .where(refresh_records_table.c.outcome == RefreshOutcomeStatus.SUCCEEDED.value)
                .order_by(
                    refresh_records_table.c.finished_at.desc(),
                    refresh_records_table.c.id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return LastSuccessfulRefresh(
            scope=RefreshScope(row["scope"]),
            sport_key=row["sport_key"],
            event_id=row["event_id"],
            finished_at=_as_utc(row["finished_at"]),
        )

    def latest_quota_observation(self) -> QuotaObservation | None:
        # Named columns: the table is read here, never shaped by this module.
        row = (
            self._require_session()
            .execute(
                select(
                    quota_observations_table.c.remaining,
                    quota_observations_table.c.used,
                    quota_observations_table.c.source,
                    quota_observations_table.c.out_of_credits,
                    quota_observations_table.c.observed_at,
                )
                .order_by(quota_observations_table.c.id.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return QuotaObservation(
            remaining=row["remaining"],
            used=row["used"],
            source=QuotaSource(row["source"]),
            out_of_credits=row["out_of_credits"],
            observed_at=_as_utc(row["observed_at"]),
        )

    def configured_quota_floor(self) -> int | None:
        return (
            self._require_session()
            .execute(select(auto_refresh_settings_table.c.quota_floor))
            .scalar_one_or_none()
        )

    def delivery_counts_since(self, since: datetime) -> dict[DeliveryStatus, int]:
        rows = self._require_session().execute(
            select(deliveries_table.c.status, func.count())
            .where(deliveries_table.c.created_at >= since)
            .group_by(deliveries_table.c.status)
        )
        return {DeliveryStatus(status): int(count) for status, count in rows}

    def pending_deliveries(self) -> PendingDeliveries:
        count, oldest = (
            self._require_session()
            .execute(
                select(func.count(), func.min(deliveries_table.c.created_at)).where(
                    deliveries_table.c.status == DeliveryStatus.PENDING.value
                )
            )
            .one()
        )
        return PendingDeliveries(
            count=int(count), oldest_created_at=None if oldest is None else _as_utc(oldest)
        )

    def _reset(self) -> None:
        # A failed statement aborts a Postgres transaction; start clean for the next read.
        try:
            self._require_session().rollback()
        except SQLAlchemyError:
            pass

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("System status read unit of work must be entered before use.")
        return self._session


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; every time this system stores is UTC.
    Aware ones are converted, so a non-UTC session time zone still serves UTC."""
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
