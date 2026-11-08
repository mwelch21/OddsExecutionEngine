"""The refresh log's one writer and the row mapping its readers share (#96)."""

from datetime import UTC, datetime

from sqlalchemy import RowMapping, insert

from backend.app.domain.refresh_records import (
    RefreshOutcomeStatus,
    RefreshRecord,
    RefreshScope,
    RefreshTrigger,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import refresh_records_table


class SqlAlchemyRefreshRecorder:
    """Appends each record in its own transaction, apart from the ingestion that
    produced it: a refresh that rolled back still leaves its record."""

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory

    def record(self, record: RefreshRecord) -> None:
        with self._session_factory.create_session() as session:
            session.execute(
                insert(refresh_records_table).values(
                    scope=record.scope.value,
                    sport_key=record.sport_key,
                    event_id=record.event_id,
                    trigger=record.trigger.value,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                    outcome=record.outcome.value,
                    error_code=record.error_code,
                    error=record.error,
                    events_refreshed=record.events_refreshed,
                )
            )
            session.commit()


def refresh_record_from_row(row: RowMapping) -> RefreshRecord:
    return RefreshRecord(
        scope=RefreshScope(row["scope"]),
        sport_key=row["sport_key"],
        event_id=row["event_id"],
        trigger=RefreshTrigger(row["trigger"]),
        started_at=_utc(row["started_at"]),
        finished_at=_utc(row["finished_at"]),
        outcome=RefreshOutcomeStatus(row["outcome"]),
        error_code=row["error_code"],
        error=row["error"],
        events_refreshed=row["events_refreshed"],
    )


def _utc(value: datetime) -> datetime:
    # SQLite hands timestamps back naive; they were written as UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)
