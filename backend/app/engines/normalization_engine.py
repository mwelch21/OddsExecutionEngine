from backend.app.domain.models import MarketType, Quote


class NormalizationEngine:
    def normalize_quotes(self, event_id: str, quotes: list[Quote]) -> list[Quote]:
        normalized_quotes: list[Quote] = []

        for quote in quotes:
            if quote.event_id != event_id:
                continue
            if not quote.sportsbook.strip() or not quote.selection.strip():
                continue
            if quote.market_type is MarketType.MONEYLINE and quote.line is not None:
                continue
            if quote.market_type in {MarketType.SPREAD, MarketType.TOTAL} and quote.line is None:
                continue
            if quote.market_type is MarketType.TOTAL and quote.selection not in {"over", "under"}:
                continue

            normalized_quotes.append(quote)

        return normalized_quotes
