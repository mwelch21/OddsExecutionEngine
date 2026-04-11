from backend.app.domain.models import ExecutionRecommendation, OrderIntent
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.infrastructure.quote_provider import QuoteProvider


class RecommendationService:
    def __init__(
        self,
        quote_provider: QuoteProvider,
        quote_matching_engine: QuoteMatchingEngine,
        recommendation_engine: RecommendationEngine,
    ) -> None:
        self._quote_provider = quote_provider
        self._quote_matching_engine = quote_matching_engine
        self._recommendation_engine = recommendation_engine

    def recommend(self, intent: OrderIntent) -> ExecutionRecommendation:
        quotes = self._quote_provider.list_quotes(intent.event_id)
        matched_quotes = self._quote_matching_engine.match_quotes(intent, quotes)
        return self._recommendation_engine.generate_recommendation(intent, matched_quotes)
