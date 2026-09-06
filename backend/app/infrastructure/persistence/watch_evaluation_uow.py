import logging

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from backend.app.application.ports import WatchEvaluationUnitOfWork
from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import OpportunitySignal, Quote, WatchIntent, WatchStatus
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.queries import (
    row_to_opportunity_signal,
    row_to_quote,
    row_to_watch_intent,
    select_latest_quotes,
)
from backend.app.infrastructure.persistence.schema import (
    opportunity_signals_table,
    watch_intents_table,
    workflow_events_table,
)


class SqlAlchemyWatchEvaluationUnitOfWork(WatchEvaluationUnitOfWork):
    _logger = logging.getLogger(__name__)

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._staged_events: list[WorkflowEvent] = []
        self._committed_events: tuple[WorkflowEvent, ...] = ()

    def __enter__(self) -> "SqlAlchemyWatchEvaluationUnitOfWork":
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
                    "watch_evaluation_uow.committed",
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
                self._logger.warning("watch_evaluation_uow.rolled_back")
        finally:
            self._staged_events = []
            session.close()
            self._session = None

    def list_active_watch_intents(self, event_id: str) -> list[WatchIntent]:
        rows = (
            self._require_session()
            .execute(
                select(watch_intents_table)
                .where(
                    watch_intents_table.c.event_external_id == event_id,
                    watch_intents_table.c.status == WatchStatus.ACTIVE.value,
                )
                .order_by(watch_intents_table.c.created_at)
            )
            .mappings()
            .all()
        )
        return [row_to_watch_intent(row) for row in rows]

    def list_quotes(self, event_id: str) -> list[Quote]:
        rows = self._require_session().execute(select_latest_quotes(event_id)).mappings().all()
        return [row_to_quote(row) for row in rows]

    def create_opportunity_signal(self, opportunity_signal: OpportunitySignal) -> None:
        self._require_session().execute(
            insert(opportunity_signals_table).values(
                id=opportunity_signal.id,
                watch_intent_id=opportunity_signal.watch_intent_id,
                event_external_id=opportunity_signal.event_id,
                market_type=opportunity_signal.market_type.value,
                selection=opportunity_signal.selection,
                line=opportunity_signal.line,
                matched_price=opportunity_signal.matched_price,
                target_price=opportunity_signal.target_price,
                sportsbook=opportunity_signal.sportsbook,
                created_at=opportunity_signal.created_at,
            )
        )

    def update_watch_intent_status(self, watch_intent_id: str, status: WatchStatus) -> None:
        self._require_session().execute(
            update(watch_intents_table)
            .where(watch_intents_table.c.id == watch_intent_id)
            .values(status=status.value)
        )

    def list_opportunity_signals(
        self,
        *,
        event_id: str | None = None,
    ) -> list[OpportunitySignal]:
        statement = select(opportunity_signals_table).order_by(
            opportunity_signals_table.c.created_at
        )
        if event_id is not None:
            statement = statement.where(
                opportunity_signals_table.c.event_external_id == event_id
            )

        rows = self._require_session().execute(statement).mappings().all()
        return [row_to_opportunity_signal(row) for row in rows]

    def get_opportunity_signal(self, opportunity_signal_id: str) -> OpportunitySignal | None:
        row = (
            self._require_session()
            .execute(
                select(opportunity_signals_table).where(
                    opportunity_signals_table.c.id == opportunity_signal_id
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else row_to_opportunity_signal(row)

    def stage_event(self, event: WorkflowEvent) -> None:
        self._staged_events.append(event)

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]:
        return self._committed_events

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Watch evaluation unit of work must be entered before use.")
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
