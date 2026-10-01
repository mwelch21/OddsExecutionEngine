import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from backend.app.application.provider_cache import ProviderPayload, ProviderResponseCache
from backend.app.domain.models import (
    EventInfo,
    EventParticipant,
    MarketType,
    ProviderFetchReport,
    Quote,
    SupportedSport,
    UpstreamQuota,
)

SPORT_LEAGUE_MAP: dict[str, tuple[str, str]] = {
    "icehockey_nhl": ("ice_hockey", "NHL"),
    "baseball_mlb": ("baseball", "MLB"),
    "basketball_nba": ("basketball", "NBA"),
    "americanfootball_nfl": ("american_football", "NFL"),
    "soccer_epl": ("soccer", "EPL"),
    "golf_pga": ("golf", "PGA"),
    "tennis_atp": ("tennis", "ATP"),
}


def _parse_timestamp(raw: object) -> datetime | None:
    """Parse an Odds API ISO-8601 timestamp, tolerating a missing or unusable one."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("odds_api.unparsable_last_update", extra={"value": raw})
        return None
    # The API reports UTC. An offsetless value left naive would be read against the
    # server's timezone once stored, shifting the very age this column exists to state.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _parse_credit_header(raw: object) -> int | None:
    """Parse a credit count, treating anything unparsable as unreported.

    The provider is not obliged to send these headers and an error response may
    carry none. None means "not reported"; it must never be flattened to 0,
    which would read as a free call or an exhausted balance.
    """
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("odds_api.unparsable_quota_header", extra={"value": raw})
        return None


def _parse_quota(headers: Mapping[str, str]) -> UpstreamQuota:
    return UpstreamQuota(
        credits_spent=_parse_credit_header(headers.get("x-requests-last")),
        credits_remaining=_parse_credit_header(headers.get("x-requests-remaining")),
    )


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
        response_cache: ProviderResponseCache,
    ) -> None:
        self._api_key = api_key
        self._sports = sports
        self._regions = ",".join(regions)
        self._markets = ",".join(markets)
        self._response_cache = response_cache
        self._client = httpx.Client(timeout=30.0)
        # Cache: event_id → EventInfo, populated on fetch
        self._event_cache: dict[str, EventInfo] = {}

    def list_quotes(self, event_id: str) -> list[Quote]:
        """Fetch quotes for a single event by its Odds API event ID."""
        for sport in self._sports:
            raw_events, _ = self._fetch_cached(sport, live=False)
            for event in raw_events:
                if event["id"] == event_id:
                    self._cache_event(event, sport)
                    return self._map_event_to_quotes(event)
        return []

    def list_events_for_sport(self, sport: str) -> list[EventInfo]:
        """Fetch all upcoming events for a sport. Returns event metadata."""
        raw_events, _ = self._fetch_cached(sport, live=False)
        events: list[EventInfo] = []
        for event in raw_events:
            info = self._cache_event(event, sport)
            events.append(info)
        return events

    def list_quotes_for_sport(
        self, sport: str
    ) -> tuple[dict[str, list[Quote]], ProviderFetchReport]:
        """Fetch all quotes for all events in a sport.

        This is the deliberate-refresh path, so it always pulls live -- it will
        never be handed a response that predates the caller. It returns the fetch
        report alongside the quotes rather than leaving it on the instance: one
        provider serves every request thread, so a stashed report would be
        clobbered by a concurrent refresh of another sport.
        """
        raw_events, report = self._fetch_cached(sport, live=True)
        result: dict[str, list[Quote]] = {}
        for event in raw_events:
            event_id = event["id"]
            self._cache_event(event, sport)
            result[event_id] = self._map_event_to_quotes(event)
        return result, report

    def get_event_info(self, event_id: str) -> EventInfo | None:
        """Get cached event metadata. Call list_events_for_sport first."""
        return self._event_cache.get(event_id)

    def list_supported_sports(self) -> list[SupportedSport]:
        """Sports this adapter can split into a sport and a league.

        Read straight off `SPORT_LEAGUE_MAP` so the catalog and the parsing
        cannot disagree. Deliberately not filtered by the configured sport list:
        that setting bounds the per-event refresh loop, and is not a whitelist.
        """
        return [
            SupportedSport(key=key, sport=sport, league=league or None)
            for key, (sport, league) in SPORT_LEAGUE_MAP.items()
        ]

    def _fetch_cached(
        self, sport: str, *, live: bool
    ) -> tuple[ProviderPayload, ProviderFetchReport]:
        """Fetch a sport's feed through the response cache.

        The quota is captured into a local rather than onto the instance, so it
        belongs to this call and cannot be read by another thread. It stays None
        when the cache answered, which is what keeps a reused response from
        reporting someone else's credit figures as though they were current.
        """
        quota: UpstreamQuota | None = None

        def load() -> ProviderPayload:
            nonlocal quota
            payload, quota = self._fetch_sport_odds(sport)
            return payload

        cached = self._response_cache.fetch(sport, load, live=live)
        report = ProviderFetchReport(
            upstream_contacted=cached.upstream_contacted,
            data_age_seconds=cached.age_seconds,
            quota=quota if cached.upstream_contacted else None,
        )
        return cached.payload, report

    def _fetch_sport_odds(self, sport: str) -> tuple[ProviderPayload, UpstreamQuota]:
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

        # Read the quota before raising: a rejected call is still a call, and
        # what it cost is exactly what an operator needs to know when upstream
        # starts failing.
        quota = _parse_quota(response.headers)
        logger.info(
            "odds_api.quota",
            extra={
                "sport": sport,
                "credits_spent": quota.credits_spent,
                "credits_remaining": quota.credits_remaining,
            },
        )

        response.raise_for_status()
        return cast(list[dict[str, Any]], response.json()), quota

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
            bookmaker_last_update = _parse_timestamp(bookmaker.get("last_update"))

            for market in bookmaker.get("markets", []):
                market_key: str = market["key"]
                market_type = MARKET_TYPE_MAP.get(market_key)
                if market_type is None:
                    continue

                # Market-level last_update is the tighter claim; the bookmaker-level
                # one covers every market it carries. Neither present means the book's
                # own line-movement time is unknown, never "just moved".
                quoted_at = _parse_timestamp(market.get("last_update")) or bookmaker_last_update

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
                            quoted_at=quoted_at,
                        )
                    )

        return quotes
