from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import RowMapping, or_, select, text
from sqlalchemy.orm import Session

from backend.app.domain.auto_refresh import (
    AutoRefreshOutcome,
    AutoRefreshSettings,
    WatchedEvent,
)
from backend.app.domain.models import EventStatus, WatchStatus, WatchWindow
from backend.app.domain.refresh_records import RefreshTrigger
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.refresh_records import refresh_record_from_row
from backend.app.infrastructure.persistence.schema import (
    auto_refresh_settings_table,
    events_table,
    refresh_records_table,
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
            live_interval_minutes=row["live_interval_minutes"],
            quota_floor=row["quota_floor"],
            sport_focus=tuple(row["sport_focus"] or ()),
        )

    def save_settings(self, settings: AutoRefreshSettings) -> AutoRefreshSettings:
        upsert(
            self._require_session(),
            auto_refresh_settings_table,
            {
                "id": SETTINGS_ROW_ID,
                "enabled": settings.enabled,
                "interval_minutes": settings.interval_minutes,
                "live_interval_minutes": settings.live_interval_minutes,
                "quota_floor": settings.quota_floor,
                "sport_focus": list(settings.sport_focus),
                "updated_at": datetime.now(UTC),
            },
            key_columns=["id"],
        )
        return self.get_settings()

    def get_last_outcome(self) -> AutoRefreshOutcome | None:
        row = (
            self._require_session()
            .execute(
                select(refresh_records_table)
                .where(refresh_records_table.c.trigger == RefreshTrigger.AUTO.value)
                .order_by(
                    refresh_records_table.c.started_at.desc(),
                    refresh_records_table.c.id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        record = refresh_record_from_row(row)
        return AutoRefreshOutcome(
            sport=record.sport_key,
            status=record.outcome,
            at=record.finished_at,
            events_refreshed=record.events_refreshed,
            error=record.error,
        )

    def list_watched_events(self, now: datetime) -> list[WatchedEvent]:
        """Active watches the candidate rule may count, with their event's status.

        A pre-filter only: stored active, TTL not passed, on an event that is not
        ended and has a stored sport (one without cannot be refreshed sport-wide).
        `AutoRefreshCandidateEngine` makes the decision from the window and status.
        """
        rows = (
            self._require_session()
            .execute(
                select(
                    events_table.c.sport,
                    events_table.c.league,
                    events_table.c.status,
                    events_table.c.starts_at,
                    watch_intents_table.c.watch_window,
                )
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
                    events_table.c.status != EventStatus.ENDED.value,
                    events_table.c.sport.is_not(None),
                )
            )
            .mappings()
            .all()
        )
        return [
            WatchedEvent(
                sport=row["sport"],
                league=row["league"],
                status=EventStatus(row["status"]),
                window=WatchWindow(row["watch_window"]),
                starts_at=row["starts_at"],
            )
            for row in rows
        ]

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
