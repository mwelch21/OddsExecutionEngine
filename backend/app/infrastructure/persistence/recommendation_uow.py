import logging
from uuid import uuid4

from sqlalchemy import insert
from sqlalchemy.orm import Session

from backend.app.application.ports import RecommendationUnitOfWork
from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import ExecutionRecommendation, OrderIntent, Quote
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.queries import row_to_quote, select_latest_quotes
from backend.app.infrastructure.persistence.schema import (
    execution_recommendations_table,
    order_intents_table,
    workflow_events_table,
)


class SqlAlchemyRecommendationUnitOfWork(RecommendationUnitOfWork):
    _logger = logging.getLogger(__name__)

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._staged_events: list[WorkflowEvent] = []
        self._committed_events: tuple[WorkflowEvent, ...] = ()

    def __enter__(self) -> "SqlAlchemyRecommendationUnitOfWork":
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
                    "recommendation_uow.committed",
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
                self._logger.warning("recommendation_uow.rolled_back")
        finally:
            self._staged_events = []
            session.close()
            self._session = None

    def create_order_intent(self, intent: OrderIntent) -> str:
        order_intent_id = str(uuid4())
        self._require_session().execute(
            insert(order_intents_table).values(
                id=order_intent_id,
                event_external_id=intent.event_id,
                market_type=intent.market_type.value,
                selection=intent.selection,
                line=intent.line,
                target_price=intent.target_price,
            )
        )
        return order_intent_id

    def list_quotes(self, event_id: str) -> list[Quote]:
        rows = self._require_session().execute(select_latest_quotes(event_id))
        return [row_to_quote(row) for row in rows.mappings().all()]

    def create_execution_recommendation(
        self,
        order_intent_id: str,
        recommendation: ExecutionRecommendation,
    ) -> str:
        recommendation_id = str(uuid4())
        self._require_session().execute(
            insert(execution_recommendations_table).values(
                id=recommendation_id,
                order_intent_id=order_intent_id,
                fillable=recommendation.fillable,
                matched_quote_count=recommendation.matched_quote_count,
                best_quote=_quote_payload(recommendation.best_quote),
                nearest_miss=_quote_payload(recommendation.nearest_miss),
                ranked_quotes=[_quote_payload(quote) for quote in recommendation.ranked_quotes],
            )
        )
        return recommendation_id

    def stage_event(self, event: WorkflowEvent) -> None:
        self._staged_events.append(event)

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]:
        return self._committed_events

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Recommendation unit of work must be entered before use.")
        return self._session

    def _persist_staged_events(self) -> None:
        if not self._staged_events:
            return

        self._logger.info(
            "recommendation_uow.persisting_events",
            extra={
                "workflow_id": self._staged_events[0].workflow_id,
                "event_count": len(self._staged_events),
            },
        )
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


def _quote_payload(quote: Quote | None) -> dict[str, object] | None:
    if quote is None:
        return None

    return {
        "event_id": quote.event_id,
        "sportsbook": quote.sportsbook,
        "market_type": quote.market_type.value,
        "selection": quote.selection,
        "price": quote.price,
        "line": quote.line,
    }
