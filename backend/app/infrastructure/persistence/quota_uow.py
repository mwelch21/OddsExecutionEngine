from datetime import UTC

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from backend.app.domain.base import DomainModel
from backend.app.domain.public_events import PublicEvent
from backend.app.domain.quota import (
    QuotaObservation,
    QuotaSource,
    UpstreamCallKind,
    UpstreamCallOutcome,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    auto_refresh_settings_table,
    public_events_table,
    quota_observations_table,
)

# Any constant works as long as nothing else in this database takes the same one.
QUOTA_LOCK_KEY = 0x0DD5_0074


class SqlAlchemyQuotaUnitOfWork:
    """Observations and the quota warning they trigger, in one transaction (ADR-014)."""

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._staged_public_events: list[PublicEvent[DomainModel]] = []

    def __enter__(self) -> "SqlAlchemyQuotaUnitOfWork":
        self._session = self._session_factory.create_session()
        self._staged_public_events = []
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        session = self._require_session()
        try:
            if exc_type is None:
                self._persist_staged_public_events()
                session.commit()
            else:
                session.rollback()
        finally:
            session.close()
            self._session = None

    def lock(self) -> None:
        """Serialize recorders until commit, so a crossing is seen exactly once.

        On SQLite (local smoke only) there is a single process; no lock is needed.
        """
        session = self._require_session()
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": QUOTA_LOCK_KEY})

    def latest_observation(self) -> QuotaObservation | None:
        row = (
            self._require_session()
            .execute(
                select(quota_observations_table)
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
            # SQLite hands timestamps back naive; they were written as UTC.
            observed_at=row["observed_at"]
            if row["observed_at"].tzinfo
            else row["observed_at"].replace(tzinfo=UTC),
            kind=UpstreamCallKind(row["call_kind"]) if row["call_kind"] else None,
            sport_key=row["sport_key"],
            event_id=row["event_id"],
            credits_spent=row["credits_spent"],
            outcome=UpstreamCallOutcome(row["call_outcome"]) if row["call_outcome"] else None,
        )

    def add_observation(self, observation: QuotaObservation) -> int:
        """Insert the observation; its id is how a refresh links to the call."""
        result = self._require_session().execute(
            insert(quota_observations_table)
            .values(
                remaining=observation.remaining,
                used=observation.used,
                source=observation.source.value,
                out_of_credits=observation.out_of_credits,
                observed_at=observation.observed_at,
                call_kind=observation.kind.value if observation.kind else None,
                sport_key=observation.sport_key,
                event_id=observation.event_id,
                credits_spent=observation.credits_spent,
                call_outcome=observation.outcome.value if observation.outcome else None,
            )
            .returning(quota_observations_table.c.id)
        )
        return int(result.scalar_one())

    def configured_floor(self) -> int | None:
        return (
            self._require_session()
            .execute(select(auto_refresh_settings_table.c.quota_floor))
            .scalar_one_or_none()
        )

    def stage_public_event(self, event: PublicEvent[DomainModel]) -> None:
        self._staged_public_events.append(event)

    def _persist_staged_public_events(self) -> None:
        if not self._staged_public_events:
            return
        self._require_session().execute(
            insert(public_events_table),
            [
                {"id": event.id, "type": event.type, "payload": event.to_cloudevent()}
                for event in self._staged_public_events
            ],
        )

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Quota unit of work must be entered before use.")
        return self._session
