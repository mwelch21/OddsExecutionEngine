import logging
from time import perf_counter

from backend.app.application.ports import (
    RecommendationUnitOfWorkFactory,
    WorkflowEventPublisher,
)
from backend.app.domain.events import (
    build_execution_recommendation_generated_event,
    build_order_intent_submitted_event,
)
from backend.app.domain.models import ExecutionRecommendation, OrderIntent
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine


class RecommendationService:
    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        unit_of_work_factory: RecommendationUnitOfWorkFactory,
        workflow_event_publisher: WorkflowEventPublisher,
        quote_matching_engine: QuoteMatchingEngine,
        recommendation_engine: RecommendationEngine,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._workflow_event_publisher = workflow_event_publisher
        self._quote_matching_engine = quote_matching_engine
        self._recommendation_engine = recommendation_engine

    def recommend(self, intent: OrderIntent) -> ExecutionRecommendation:
        started_at = perf_counter()
        order_intent_id = "-"
        recommendation_id = "-"

        self._logger.info(
            "recommendation.started",
            extra={
                "path": "/execution/recommendation",
                "event_id": intent.event_id,
                "market_type": intent.market_type.value,
                "selection": intent.selection,
            },
        )

        try:
            with self._unit_of_work_factory() as unit_of_work:
                order_intent_id = unit_of_work.create_order_intent(intent)
                unit_of_work.stage_event(
                    build_order_intent_submitted_event(
                        order_intent_id=order_intent_id,
                        intent=intent,
                    )
                )
                quotes = unit_of_work.list_quotes(intent.event_id)
                matched_quotes = self._quote_matching_engine.match_quotes(intent, quotes)
                recommendation = self._recommendation_engine.generate_recommendation(
                    intent,
                    matched_quotes,
                )
                recommendation_id = unit_of_work.create_execution_recommendation(
                    order_intent_id,
                    recommendation,
                )
                unit_of_work.stage_event(
                    build_execution_recommendation_generated_event(
                        order_intent_id=order_intent_id,
                        recommendation_id=recommendation_id,
                        recommendation=recommendation,
                    )
                )

            self._workflow_event_publisher.publish(unit_of_work.committed_events)
        except Exception:
            self._logger.exception(
                "recommendation.failed",
                extra={
                    "workflow_id": order_intent_id,
                    "order_intent_id": order_intent_id,
                    "recommendation_id": recommendation_id,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise

        self._logger.info(
            "recommendation.completed",
            extra={
                "workflow_id": order_intent_id,
                "order_intent_id": order_intent_id,
                "recommendation_id": recommendation_id,
                "event_count": len(unit_of_work.committed_events),
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return recommendation
