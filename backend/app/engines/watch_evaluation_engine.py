from datetime import datetime

from backend.app.domain.models import (
    Quote,
    TriggeredWatch,
    WatchEvaluationResult,
    WatchIntent,
)
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine


class WatchEvaluationEngine:
    def __init__(
        self,
        quote_matching_engine: QuoteMatchingEngine,
        recommendation_engine: RecommendationEngine,
        price_comparison_service: PriceComparisonService,
    ) -> None:
        self._quote_matching_engine = quote_matching_engine
        self._recommendation_engine = recommendation_engine
        self._price_comparison_service = price_comparison_service

    def evaluate(
        self,
        watch_intents: list[WatchIntent],
        quotes: list[Quote],
        *,
        now: datetime,
    ) -> WatchEvaluationResult:
        expired: list[WatchIntent] = []
        triggered: list[TriggeredWatch] = []

        for watch_intent in watch_intents:
            if _is_expired(watch_intent, now):
                expired.append(watch_intent)
                continue

            triggering_quote = self._find_triggering_quote(watch_intent, quotes)
            if triggering_quote is not None:
                triggered.append(
                    TriggeredWatch(watch_intent=watch_intent, quote=triggering_quote)
                )

        return WatchEvaluationResult(triggered=triggered, expired=expired)

    def _find_triggering_quote(
        self,
        watch_intent: WatchIntent,
        quotes: list[Quote],
    ) -> Quote | None:
        matched_quotes = self._quote_matching_engine.match_quotes(watch_intent, quotes)
        fillable_quotes = [
            quote
            for quote in matched_quotes
            if self._price_comparison_service.is_price_fillable(
                quote.price,
                watch_intent.target_price,
            )
        ]
        ranked_quotes = self._recommendation_engine.rank_quotes(fillable_quotes)
        return ranked_quotes[0] if ranked_quotes else None


def _is_expired(watch_intent: WatchIntent, now: datetime) -> bool:
    return watch_intent.expires_at is not None and watch_intent.expires_at <= now
