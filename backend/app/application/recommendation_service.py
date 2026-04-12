from backend.app.application.ports import RecommendationUnitOfWorkFactory
from backend.app.domain.models import ExecutionRecommendation, OrderIntent
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine


class RecommendationService:
    def __init__(
        self,
        unit_of_work_factory: RecommendationUnitOfWorkFactory,
        quote_matching_engine: QuoteMatchingEngine,
        recommendation_engine: RecommendationEngine,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._quote_matching_engine = quote_matching_engine
        self._recommendation_engine = recommendation_engine

    def recommend(self, intent: OrderIntent) -> ExecutionRecommendation:
        with self._unit_of_work_factory() as unit_of_work:
            order_intent_id = unit_of_work.create_order_intent(intent)
            quotes = unit_of_work.list_quotes(intent.event_id)
            matched_quotes = self._quote_matching_engine.match_quotes(intent, quotes)
            recommendation = self._recommendation_engine.generate_recommendation(
                intent,
                matched_quotes,
            )
            unit_of_work.create_execution_recommendation(order_intent_id, recommendation)
            return recommendation
