from uuid import uuid4

from backend.app.domain.models import (
    MarketType,
    MatchingQuote,
    Opportunity,
    Quote,
    WatchIntent,
    WatchStatus,
)
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.recommendation_engine import RecommendationEngine


def _market_lookup_key(
    event_id: str,
    market_type: MarketType,
    selection: str,
    line: float | None,
) -> tuple[str, str, str, float | None]:
    return (event_id, market_type.value, selection, line)


class WatchEvaluationEngine:
    def __init__(
        self,
        price_comparison_service: PriceComparisonService,
        recommendation_engine: RecommendationEngine,
    ) -> None:
        self._price_comparison = price_comparison_service
        self._recommendation_engine = recommendation_engine

    def evaluate(
        self,
        watch_intents: list[WatchIntent],
        quotes: list[Quote],
        market_id_lookup: dict[tuple[str, str, str, float | None], str],
    ) -> list[Opportunity]:
        """Evaluate watch intents against quotes, one opportunity per watch.

        A watch names exactly one market, so every fillable quote it matches is a
        competing book on that market. They collapse into a single opportunity whose
        `matching_quotes` lists them all ranked best-first, rather than one
        notification per book.

        No deduplication happens here: a watch is terminal once it fires, so a
        triggered watch never reaches this engine again. The unique constraint on
        `opportunities.watch_intent_id` is the real guard.

        Args:
            watch_intents: Watch intents to evaluate. Non-active ones are skipped.
            quotes: Available quotes from the market.
            market_id_lookup: Mapping of (event_id, market_type, selection, line)
                to market_id. Provided by the UoW/caller.
        """
        opportunities: list[Opportunity] = []

        for intent in watch_intents:
            if intent.status is not WatchStatus.ACTIVE:
                continue

            fillable = [
                quote
                for quote in quotes
                if quote.event_id == intent.event_id
                and quote.market_type == intent.market_type
                and quote.selection == intent.selection
                and quote.line == intent.line
                and self._price_comparison.is_price_fillable(
                    quote.price, intent.target_price
                )
            ]
            if not fillable:
                continue

            # Ties resolve by sportsbook name so the same market state always names
            # the same best book.
            ranked = self._recommendation_engine.rank_quotes(fillable)
            best = ranked[0]

            # Keyed off the intent, not the ranked head: the watch names the market,
            # so the lookup must not depend on which book happened to win.
            lookup_key = _market_lookup_key(
                intent.event_id, intent.market_type, intent.selection, intent.line
            )
            market_id = market_id_lookup.get(lookup_key, "")
            if not market_id:
                continue

            opportunities.append(
                Opportunity(
                    id=str(uuid4()),
                    watch_intent_id=intent.id,
                    event_id=intent.event_id,
                    market_id=market_id,
                    market_type=intent.market_type,
                    selection=intent.selection,
                    target_price=intent.target_price,
                    best_sportsbook=best.sportsbook,
                    best_price=best.price,
                    matching_quotes=[
                        MatchingQuote(sportsbook=quote.sportsbook, price=quote.price)
                        for quote in ranked
                    ],
                    line=intent.line,
                )
            )

        return opportunities
