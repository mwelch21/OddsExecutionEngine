from backend.app.domain.models import ExecutionRecommendation, OrderIntent, Quote
from backend.app.engines.price_comparison_engine import PriceComparisonService


class RecommendationEngine:
    def __init__(self, price_comparison_service: PriceComparisonService) -> None:
        self._price_comparison_service = price_comparison_service

    def rank_quotes(self, quotes: list[Quote]) -> list[Quote]:
        return sorted(quotes, key=lambda quote: (-quote.price, quote.sportsbook))

    def generate_recommendation(
        self,
        intent: OrderIntent,
        matched_quotes: list[Quote],
    ) -> ExecutionRecommendation:
        ranked_quotes = self.rank_quotes(matched_quotes)
        best_quote = ranked_quotes[0] if ranked_quotes else None
        fillable_quotes = [
            quote
            for quote in ranked_quotes
            if self._price_comparison_service.is_price_fillable(
                quote.price, intent.target_price
            )
        ]
        nearest_miss = next(
            (
                quote
                for quote in ranked_quotes
                if not self._price_comparison_service.is_price_fillable(
                    quote.price, intent.target_price
                )
            ),
            None,
        )

        return ExecutionRecommendation(
            intent=intent,
            fillable=bool(fillable_quotes),
            best_quote=fillable_quotes[0] if fillable_quotes else best_quote,
            ranked_quotes=ranked_quotes,
            nearest_miss=None if fillable_quotes else nearest_miss,
            matched_quote_count=len(ranked_quotes),
        )
