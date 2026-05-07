from datetime import UTC, datetime, timedelta

from backend.app.domain.models import EventInfo, EventParticipant, MarketType, Quote

FIXTURE_EVENT_ID = "nba-knicks-celtics-2026-04-11"
FIXTURE_SPORT = "basketball_nba"


class InMemoryQuoteProvider:
    def __init__(self, quotes: list[Quote] | None = None) -> None:
        self._quotes = quotes or build_fixture_quotes()
        self._events = _build_fixture_events()

    def list_quotes(self, event_id: str) -> list[Quote]:
        return [quote for quote in self._quotes if quote.event_id == event_id]

    def list_quotes_for_sport(self, sport: str) -> dict[str, list[Quote]]:
        event_ids = {e.id for e in self._events.values() if e.sport == sport}
        result: dict[str, list[Quote]] = {}
        for quote in self._quotes:
            if quote.event_id in event_ids:
                result.setdefault(quote.event_id, []).append(quote)
        return result

    def get_event_info(self, event_id: str) -> EventInfo | None:
        return self._events.get(event_id)


def _build_fixture_events() -> dict[str, EventInfo]:
    return {
        FIXTURE_EVENT_ID: EventInfo(
            id=FIXTURE_EVENT_ID,
            sport="basketball",
            league="NBA",
            participants=[
                EventParticipant(name="Celtics", role="team", side="home", sort_order=1),
                EventParticipant(name="Knicks", role="team", side="away", sort_order=2),
            ],
            commence_time=datetime.now(UTC) + timedelta(days=3),
        ),
    }


def build_fixture_quotes() -> list[Quote]:
    event_id = FIXTURE_EVENT_ID

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
