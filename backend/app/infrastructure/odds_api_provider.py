import logging
from datetime import datetime

import httpx

from backend.app.domain.models import EventInfo, EventParticipant, MarketType, Quote

SPORT_LEAGUE_MAP: dict[str, tuple[str, str]] = {
    "icehockey_nhl": ("ice_hockey", "NHL"),
    "baseball_mlb": ("baseball", "MLB"),
    "basketball_nba": ("basketball", "NBA"),
    "americanfootball_nfl": ("american_football", "NFL"),
    "soccer_epl": ("soccer", "EPL"),
    "golf_pga": ("golf", "PGA"),
    "tennis_atp": ("tennis", "ATP"),
}


def _parse_sport_league(sport_key: str) -> tuple[str, str]:
    """Split Odds API sport key into (sport, league)."""
    if sport_key in SPORT_LEAGUE_MAP:
        return SPORT_LEAGUE_MAP[sport_key]
    parts = sport_key.rsplit("_", 1)
    if len(parts) == 2:
        return parts[0].replace("_", "_"), parts[1].upper()
    return sport_key, ""

logger = logging.getLogger(__name__)

ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports"

MARKET_TYPE_MAP: dict[str, MarketType] = {
    "h2h": MarketType.MONEYLINE,
    "spreads": MarketType.SPREAD,
    "totals": MarketType.TOTAL,
}


class TheOddsApiProvider:
    """Implements QuoteIngestionProvider protocol using The Odds API."""

    def __init__(
        self,
        api_key: str,
        sports: list[str],
        regions: list[str],
        markets: list[str],
    ) -> None:
        self._api_key = api_key
        self._sports = sports
        self._regions = ",".join(regions)
        self._markets = ",".join(markets)
        self._client = httpx.Client(timeout=30.0)
        # Cache: event_id → EventInfo, populated on fetch
        self._event_cache: dict[str, EventInfo] = {}

    def list_quotes(self, event_id: str) -> list[Quote]:
        """Fetch quotes for a single event by its Odds API event ID."""
        for sport in self._sports:
            raw_events = self._fetch_sport_odds(sport)
            for event in raw_events:
                if event["id"] == event_id:
                    self._cache_event(event, sport)
                    return self._map_event_to_quotes(event)
        return []

    def list_events_for_sport(self, sport: str) -> list[EventInfo]:
        """Fetch all upcoming events for a sport. Returns event metadata."""
        raw_events = self._fetch_sport_odds(sport)
        events: list[EventInfo] = []
        for event in raw_events:
            info = self._cache_event(event, sport)
            events.append(info)
        return events

    def list_quotes_for_sport(self, sport: str) -> dict[str, list[Quote]]:
        """Fetch all quotes for all events in a sport.

        Returns dict of event_id → quotes. Single API call per sport.
        """
        raw_events = self._fetch_sport_odds(sport)
        result: dict[str, list[Quote]] = {}
        for event in raw_events:
            event_id = event["id"]
            self._cache_event(event, sport)
            result[event_id] = self._map_event_to_quotes(event)
        return result

    def get_event_info(self, event_id: str) -> EventInfo | None:
        """Get cached event metadata. Call list_events_for_sport first."""
        return self._event_cache.get(event_id)

    def _fetch_sport_odds(self, sport: str) -> list[dict]:
        """GET /v4/sports/{sport}/odds from The Odds API."""
        url = f"{ODDS_API_BASE}/{sport}/odds"
        params = {
            "apiKey": self._api_key,
            "regions": self._regions,
            "markets": self._markets,
            "oddsFormat": "american",
        }
        logger.info(
            "odds_api.fetch",
            extra={"sport": sport, "url": url},
        )
        response = self._client.get(url, params=params)
        response.raise_for_status()

        remaining = response.headers.get("x-requests-remaining", "?")
        used = response.headers.get("x-requests-used", "?")
        logger.info(
            "odds_api.quota",
            extra={
                "sport": sport,
                "requests_remaining": remaining,
                "requests_used": used,
            },
        )

        return response.json()

    def _cache_event(self, event: dict, sport_key: str) -> EventInfo:
        """Extract and cache event metadata."""
        sport, league = _parse_sport_league(sport_key)
        participants: list[EventParticipant] = []
        home = event.get("home_team")
        away = event.get("away_team")
        if home:
            participants.append(
                EventParticipant(name=home, role="team", side="home", sort_order=1)
            )
        if away:
            participants.append(
                EventParticipant(name=away, role="team", side="away", sort_order=2)
            )
        info = EventInfo(
            id=event["id"],
            sport=sport,
            league=league,
            participants=participants,
            commence_time=datetime.fromisoformat(
                event["commence_time"].replace("Z", "+00:00")
            ),
        )
        self._event_cache[info.id] = info
        return info

    def _map_event_to_quotes(self, event: dict) -> list[Quote]:
        """Map a single Odds API event response to domain Quote objects."""
        event_id: str = event["id"]
        quotes: list[Quote] = []

        for bookmaker in event.get("bookmakers", []):
            sportsbook: str = bookmaker["key"]

            for market in bookmaker.get("markets", []):
                market_key: str = market["key"]
                market_type = MARKET_TYPE_MAP.get(market_key)
                if market_type is None:
                    continue

                for outcome in market.get("outcomes", []):
                    price = outcome.get("price")
                    if price is None:
                        continue

                    selection = outcome["name"].lower()
                    line: float | None = outcome.get("point")

                    # Totals: selection is "Over"/"Under" from API
                    if market_type is MarketType.TOTAL:
                        if selection not in ("over", "under"):
                            continue

                    # Moneyline: no line
                    if market_type is MarketType.MONEYLINE:
                        line = None

                    quotes.append(
                        Quote(
                            event_id=event_id,
                            sportsbook=sportsbook,
                            market_type=market_type,
                            selection=selection,
                            price=int(price),
                            line=line,
                        )
                    )

        return quotes
