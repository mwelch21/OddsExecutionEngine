import logging
from datetime import UTC, datetime

from sqlalchemy import RowMapping, insert, select, update
from sqlalchemy.orm import Session

from backend.app.application.ports import WatchIntentUnitOfWork
from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import MarketType, WatchIntent, WatchStatus
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    watch_intents_table,
    workflow_events_table,
)


class SqlAlchemyWatchIntentUnitOfWork(WatchIntentUnitOfWork):
    _logger = logging.getLogger(__name__)

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._staged_events: list[WorkflowEvent] = []
        self._committed_events: tuple[WorkflowEvent, ...] = ()

    def __enter__(self) -> "SqlAlchemyWatchIntentUnitOfWork":
        self._session = self._session_factory.create_session()
        self._staged_events = []
        self._committed_events = ()
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
                self._persist_staged_events()
                session.commit()
                self._committed_events = tuple(self._staged_events)
                self._logger.info(
                    "watch_intent_uow.committed",
                    extra={
                        "workflow_id": (
                            self._committed_events[0].workflow_id if self._committed_events else "-"
                        ),
                        "event_count": len(self._committed_events),
                    },
                )
            else:
                session.rollback()
                self._committed_events = ()
                self._logger.warning("watch_intent_uow.rolled_back")
        finally:
            self._staged_events = []
            session.close()
            self._session = None

    def create_watch_intent(self, watch_intent: WatchIntent) -> None:
        self._require_session().execute(
            insert(watch_intents_table).values(
                id=watch_intent.id,
                event_external_id=watch_intent.event_id,
                market_type=watch_intent.market_type.value,
                selection=watch_intent.selection,
                line=watch_intent.line,
                target_price=watch_intent.target_price,
                expires_at=watch_intent.expires_at,
                status=watch_intent.status.value,
                created_at=watch_intent.created_at,
            )
        )

    def list_watch_intents(
        self,
        *,
        event_id: str | None = None,
        status: WatchStatus | None = None,
    ) -> list[WatchIntent]:
        statement = select(watch_intents_table).order_by(watch_intents_table.c.created_at)
        if event_id is not None:
            statement = statement.where(watch_intents_table.c.event_external_id == event_id)
        if status is not None:
            statement = statement.where(watch_intents_table.c.status == status.value)

        rows = self._require_session().execute(statement).mappings().all()
        return [_row_to_watch_intent(row) for row in rows]

    def get_watch_intent(self, watch_intent_id: str) -> WatchIntent | None:
        row = (
            self._require_session()
            .execute(select(watch_intents_table).where(watch_intents_table.c.id == watch_intent_id))
            .mappings()
            .first()
        )
        return None if row is None else _row_to_watch_intent(row)

    def update_watch_intent_status(self, watch_intent_id: str, status: WatchStatus) -> None:
        self._require_session().execute(
            update(watch_intents_table)
            .where(watch_intents_table.c.id == watch_intent_id)
            .values(status=status.value)
        )

    def stage_event(self, event: WorkflowEvent) -> None:
        self._staged_events.append(event)

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]:
        return self._committed_events

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Watch intent unit of work must be entered before use.")
        return self._session

    def _persist_staged_events(self) -> None:
        if not self._staged_events:
            return

        self._require_session().execute(
            insert(workflow_events_table),
            [
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "aggregate_id": event.aggregate_id,
                    "workflow_id": event.workflow_id,
                    "payload": event.payload.model_dump(mode="json"),
                    "occurred_at": event.occurred_at,
                }
                for event in self._staged_events
            ],
        )


def _row_to_watch_intent(row: RowMapping) -> WatchIntent:
    return WatchIntent(
        id=row["id"],
        event_id=row["event_external_id"],
        market_type=MarketType(row["market_type"]),
        selection=row["selection"],
        target_price=row["target_price"],
        line=row["line"],
        expires_at=as_utc(row["expires_at"]),
        status=WatchStatus(row["status"]),
        created_at=as_utc(row["created_at"]) or datetime.now(UTC),
    )


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)
