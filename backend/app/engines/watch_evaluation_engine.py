from uuid import uuid4

from backend.app.domain.models import MarketType, Opportunity, Quote, WatchIntent
from backend.app.engines.price_comparison_engine import PriceComparisonService


def _market_lookup_key(
    event_id: str,
    market_type: MarketType,
    selection: str,
    line: float | None,
) -> tuple[str, str, str, float | None]:
    return (event_id, market_type.value, selection, line)


class WatchEvaluationEngine:
    def __init__(self, price_comparison_service: PriceComparisonService) -> None:
        self._price_comparison = price_comparison_service

    def evaluate(
        self,
        watch_intents: list[WatchIntent],
        quotes: list[Quote],
        market_id_lookup: dict[tuple[str, str, str, float | None], str],
        existing_opportunity_keys: set[tuple[str, str, str]] | None = None,
    ) -> list[Opportunity]:
        """Evaluate watch intents against quotes and produce opportunities.

        Args:
            watch_intents: Active watch intents to evaluate.
            quotes: Available quotes from the market.
            market_id_lookup: Mapping of (event_id, market_type, selection, line)
                to market_id. Provided by the UoW/caller.
            existing_opportunity_keys: Set of (watch_intent_id, market_id, sportsbook)
                tuples for deduplication. Opportunities matching these keys are skipped.
        """
        keys = existing_opportunity_keys or set()
        opportunities: list[Opportunity] = []

        for intent in watch_intents:
            if intent.status != "active":
                continue

            matched = [
                q
                for q in quotes
                if q.event_id == intent.event_id
                and q.market_type == intent.market_type
                and q.selection == intent.selection
                and q.line == intent.line
            ]

            for quote in matched:
                if not self._price_comparison.is_price_fillable(
                    quote.price, intent.target_price
                ):
                    continue

                lookup_key = _market_lookup_key(
                    quote.event_id, quote.market_type, quote.selection, quote.line
                )
                market_id = market_id_lookup.get(lookup_key, "")
                if not market_id:
                    continue

                dedup_key = (intent.id, market_id, quote.sportsbook)
                if dedup_key in keys:
                    continue
                keys.add(dedup_key)

                opportunities.append(
                    Opportunity(
                        id=str(uuid4()),
                        watch_intent_id=intent.id,
                        event_id=intent.event_id,
                        market_id=market_id,
                        market_type=intent.market_type,
                        selection=intent.selection,
                        target_price=intent.target_price,
                        sportsbook=quote.sportsbook,
                        matched_price=quote.price,
                        line=intent.line,
                    )
                )

        return opportunities
