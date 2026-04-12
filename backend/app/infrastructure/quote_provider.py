from backend.app.domain.models import MarketType, Quote


class InMemoryQuoteProvider:
    def __init__(self, quotes: list[Quote] | None = None) -> None:
        self._quotes = quotes or build_fixture_quotes()

    def list_quotes(self, event_id: str) -> list[Quote]:
        return [quote for quote in self._quotes if quote.event_id == event_id]


def build_fixture_quotes() -> list[Quote]:
    event_id = "nba-knicks-celtics-2026-04-11"

    return [
        Quote(
            event_id=event_id,
            sportsbook="BetMGM",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=120,
        ),
        Quote(
            event_id=event_id,
            sportsbook="DraftKings",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=125,
        ),
        Quote(
            event_id=event_id,
            sportsbook="FanDuel",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=125,
        ),
        Quote(
            event_id=event_id,
            sportsbook="Caesars",
            market_type=MarketType.MONEYLINE,
            selection="celtics",
            price=-145,
        ),
        Quote(
            event_id=event_id,
            sportsbook="DraftKings",
            market_type=MarketType.SPREAD,
            selection="knicks",
            line=5.5,
            price=-108,
        ),
        Quote(
            event_id=event_id,
            sportsbook="FanDuel",
            market_type=MarketType.SPREAD,
            selection="knicks",
            line=5.5,
            price=-110,
        ),
        Quote(
            event_id=event_id,
            sportsbook="BetMGM",
            market_type=MarketType.SPREAD,
            selection="knicks",
            line=4.5,
            price=-102,
        ),
        Quote(
            event_id=event_id,
            sportsbook="DraftKings",
            market_type=MarketType.TOTAL,
            selection="over",
            line=221.5,
            price=-112,
        ),
        Quote(
            event_id=event_id,
            sportsbook="FanDuel",
            market_type=MarketType.TOTAL,
            selection="over",
            line=221.5,
            price=-108,
        ),
        Quote(
            event_id=event_id,
            sportsbook="BetMGM",
            market_type=MarketType.TOTAL,
            selection="under",
            line=221.5,
            price=-105,
        ),
    ]
