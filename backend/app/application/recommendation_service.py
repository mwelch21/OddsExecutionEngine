from backend.app.domain.models import ExecutionRecommendation, OrderIntent
from backend.app.engines.quote_matching_engine import match_quotes
from backend.app.engines.recommendation_engine import generate_recommendation
from backend.app.infrastructure.quote_provider import QuoteProvider


class RecommendationService:
    def __init__(self, quote_provider: QuoteProvider) -> None:
        self._quote_provider = quote_provider

    def recommend(self, intent: OrderIntent) -> ExecutionRecommendation:
        quotes = self._quote_provider.list_quotes(intent.event_id)
        matched_quotes = match_quotes(intent, quotes)
        return generate_recommendation(intent, matched_quotes)
