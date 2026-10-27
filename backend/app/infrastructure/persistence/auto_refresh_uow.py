from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import RowMapping, or_, select, text
from sqlalchemy.orm import Session

from backend.app.domain.auto_refresh import (
    AutoRefreshOutcome,
    AutoRefreshSettings,
    RefreshOutcomeStatus,
)
from backend.app.domain.models import EventSport, WatchStatus
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    auto_refresh_settings_table,
    events_table,
    sport_refreshes_table,
    watch_intents_table,
)
from backend.app.infrastructure.persistence.upsert import upsert

SETTINGS_ROW_ID = 1

# Any constant works as long as nothing else in this database takes the same one.
AUTO_REFRESH_LOCK_KEY = 0x0DD5_0016


class SqlAlchemyAutoRefreshUnitOfWork:
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> "SqlAlchemyAutoRefreshUnitOfWork":
        self._session = self._session_factory.create_session()
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
                session.commit()
            else:
                session.rollback()
        finally:
            session.close()
            self._session = None

    def get_settings(self) -> AutoRefreshSettings:
        row = self._settings_row()
        if row is None:
            return AutoRefreshSettings()
        return AutoRefreshSettings(
            enabled=row["enabled"],
            interval_minutes=row["interval_minutes"],
            quota_floor=row["quota_floor"],
        )

    def save_settings(self, settings: AutoRefreshSettings) -> AutoRefreshSettings:
        upsert(
            self._require_session(),
            auto_refresh_settings_table,
            {
                "id": SETTINGS_ROW_ID,
                "enabled": settings.enabled,
                "interval_minutes": settings.interval_minutes,
                "quota_floor": settings.quota_floor,
                "updated_at": datetime.now(UTC),
            },
            key_columns=["id"],
        )
        return self.get_settings()

    def get_last_outcome(self) -> AutoRefreshOutcome | None:
        row = self._settings_row()
        if row is None or row["last_outcome_at"] is None:
            return None
        return AutoRefreshOutcome(
            sport=row["last_outcome_sport"],
            status=RefreshOutcomeStatus(row["last_outcome_status"]),
            at=row["last_outcome_at"],
            events_refreshed=row["last_outcome_events_refreshed"] or 0,
            error=row["last_outcome_error"],
        )

    def record_outcome(self, outcome: AutoRefreshOutcome) -> None:
        # Settings are carried over unchanged: recording an outcome must never
        # flip the operator's switch, even on a database with no row yet.
        settings = self.get_settings()
        upsert(
            self._require_session(),
            auto_refresh_settings_table,
            {
                "id": SETTINGS_ROW_ID,
                "enabled": settings.enabled,
                "interval_minutes": settings.interval_minutes,
                "quota_floor": settings.quota_floor,
                "last_outcome_sport": outcome.sport,
                "last_outcome_status": outcome.status.value,
                "last_outcome_at": outcome.at,
                "last_outcome_events_refreshed": outcome.events_refreshed,
                "last_outcome_error": outcome.error,
            },
            key_columns=["id"],
        )

    def list_watched_event_sports(self, now: datetime) -> list[EventSport]:
        """The sports of events with a watch the evaluator will act on.

        Mirrors `WatchIntentService.evaluate_for_event`: stored active, TTL not
        passed, and on an event that has not started. A watch on an event with no
        stored sport cannot be refreshed sport-wide and is left out.
        """
        rows = (
            self._require_session()
            .execute(
                select(events_table.c.sport, events_table.c.league)
                .distinct()
                .select_from(
                    watch_intents_table.join(
                        events_table,
                        watch_intents_table.c.event_external_id
                        == events_table.c.external_id,
                    )
                )
                .where(
                    watch_intents_table.c.status == WatchStatus.ACTIVE.value,
                    or_(
                        watch_intents_table.c.expires_at.is_(None),
                        watch_intents_table.c.expires_at > now,
                    ),
                    or_(events_table.c.starts_at.is_(None), events_table.c.starts_at > now),
                    events_table.c.sport.is_not(None),
                )
            )
            .mappings()
            .all()
        )
        return [EventSport(sport=row["sport"], league=row["league"]) for row in rows]

    def get_sport_refresh_times(self) -> dict[str, datetime]:
        rows = self._require_session().execute(select(sport_refreshes_table)).mappings().all()
        return {row["sport_key"]: row["last_refreshed_at"] for row in rows}

    def _settings_row(self) -> RowMapping | None:
        return (
            self._require_session()
            .execute(
                select(auto_refresh_settings_table).where(
                    auto_refresh_settings_table.c.id == SETTINGS_ROW_ID
                )
            )
            .mappings()
            .one_or_none()
        )

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Auto-Refresh unit of work must be entered before use.")
        return self._session


class PostgresAdvisoryCycleLock:
    """A session-level advisory lock held on one connection for the whole cycle.

    Non-blocking: a second worker gets False and skips the poll instead of queueing
    a duplicate refresh behind the first. On SQLite (local smoke only) there is a
    single process, so the lock is always granted.
    """

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._engine = session_factory.engine

    @contextmanager
    def hold(self) -> Iterator[bool]:
        if self._engine.dialect.name != "postgresql":
            yield True
            return
        with self._engine.connect() as connection:
            acquired = bool(
                connection.execute(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": AUTO_REFRESH_LOCK_KEY}
                ).scalar()
            )
            connection.commit()
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": AUTO_REFRESH_LOCK_KEY}
                    )
                    connection.commit()
