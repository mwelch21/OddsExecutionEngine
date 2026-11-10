import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from backend.app.application.ports import QuotaRecorder
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
from backend.app.domain.quota import (
    OutOfUsageCreditsError,
    QuotaReading,
    UpstreamCallKind,
    UpstreamCallOutcome,
    link_observation,
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


def _is_out_of_credits(response: httpx.Response) -> bool:
    """Matched on the body's `error_code`: the docs give no status code for it."""
    if response.is_success:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("error_code") == "OUT_OF_USAGE_CREDITS"


def _call_outcome(response: httpx.Response) -> UpstreamCallOutcome:
    """How a call that got a response ended (#121)."""
    if _is_out_of_credits(response):
        return UpstreamCallOutcome.OUT_OF_CREDITS
    if response.is_success:
        return UpstreamCallOutcome.ANSWERED
    if response.status_code in (401, 403):
        return UpstreamCallOutcome.AUTH_FAILURE
    if 400 <= response.status_code < 500:
        return UpstreamCallOutcome.CLIENT_ERROR
    # 5xx, or anything else that is neither an answer nor a rejection of our request.
    return UpstreamCallOutcome.SERVER_ERROR


def _raise_for_status(response: httpx.Response) -> None:
    if _is_out_of_credits(response):
        raise OutOfUsageCreditsError()
    response.raise_for_status()


def _checked_json(response: httpx.Response, observation_id: int | None) -> Any:
    """The body of a successful response. A raise names the call it followed, so the
    refresh that paid for the call still links to it."""
    try:
        _raise_for_status(response)
        return response.json()
    except Exception as error:
        link_observation(error, observation_id)
        raise


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
        regions: list[str],
        markets: list[str],
        response_cache: ProviderResponseCache,
        quota_recorder: QuotaRecorder | None = None,
    ) -> None:
        self._api_key = api_key
        self._regions = ",".join(regions)
        self._markets = ",".join(markets)
        # The local fallback when headers are absent: a call bills markets x regions.
        self._call_cost = len(markets) * len(regions)
        self._response_cache = response_cache
        self._quota_recorder = quota_recorder
        self._client = httpx.Client(timeout=30.0)
        # Cache: event_id → EventInfo, populated on fetch
        self._event_cache: dict[str, EventInfo] = {}

    def list_quotes(
        self, event_id: str, sport: str
    ) -> tuple[list[Quote], ProviderFetchReport]:
        """Fetch one event's quotes in a single call to the single-event endpoint.

        This is a deliberate refresh, so it pulls live; the cache only coalesces
        simultaneous refreshes of the same event. The caller supplies the sport --
        scanning sport feeds to find the event is what made one event cost more
        than a whole sport.
        """
        raw_events, report = self._fetch_cached(
            f"event:{sport}:{event_id}",
            lambda: self._fetch_event_odds(sport, event_id),
            live=True,
        )
        quotes: list[Quote] = []
        try:
            for event in raw_events:
                self._cache_event(event, sport)
                quotes.extend(self._map_event_to_quotes(event))
        except Exception as error:
            # The call was billed before its body proved unusable.
            link_observation(error, report.observation_id)
            raise
        return quotes, report

    def list_events_for_sport(self, sport: str) -> list[EventInfo]:
        """Fetch all upcoming events for a sport. Returns event metadata."""
        raw_events, _ = self._fetch_cached(
            sport, lambda: self._fetch_sport_odds(sport), live=False
        )
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
        raw_events, report = self._fetch_cached(
            sport, lambda: self._fetch_sport_odds(sport), live=True
        )
        result: dict[str, list[Quote]] = {}
        try:
            for event in raw_events:
                event_id = event["id"]
                self._cache_event(event, sport)
                result[event_id] = self._map_event_to_quotes(event)
        except Exception as error:
            # The call was billed before its body proved unusable.
            link_observation(error, report.observation_id)
            raise
        return result, report

    def get_event_info(self, event_id: str) -> EventInfo | None:
        """Get cached event metadata. Call list_events_for_sport first."""
        return self._event_cache.get(event_id)

    def list_supported_sports(self) -> list[SupportedSport]:
        """Sports this adapter can split into a sport and a league.

        Read straight off `SPORT_LEAGUE_MAP` so the catalog and the parsing
        cannot disagree.
        """
        return [
            SupportedSport(key=key, sport=sport, league=league or None)
            for key, (sport, league) in SPORT_LEAGUE_MAP.items()
        ]

    def _fetch_cached(
        self,
        key: str,
        fetch: Callable[[], tuple[ProviderPayload, UpstreamQuota, int | None]],
        *,
        live: bool,
    ) -> tuple[ProviderPayload, ProviderFetchReport]:
        """Fetch a payload through the response cache.

        The quota is captured into a local rather than onto the instance, so it
        belongs to this call and cannot be read by another thread. It stays None
        when the cache answered, which is what keeps a reused response from
        reporting someone else's credit figures as though they were current.

        The observation id is stored beside the payload instead: it names the call
        the data came from, so callers coalesced onto that call all link to it.
        """
        quota: UpstreamQuota | None = None

        def load() -> tuple[ProviderPayload, int | None]:
            nonlocal quota
            payload, quota, observation_id = fetch()
            return payload, observation_id

        cached = self._response_cache.fetch(key, load, live=live)
        payload, observation_id = cached.payload
        report = ProviderFetchReport(
            upstream_contacted=cached.upstream_contacted,
            data_age_seconds=cached.age_seconds,
            quota=quota if cached.upstream_contacted else None,
            observation_id=observation_id,
        )
        return payload, report

    def _fetch_sport_odds(
        self, sport: str
    ) -> tuple[ProviderPayload, UpstreamQuota, int | None]:
        """GET /v4/sports/{sport}/odds from The Odds API."""
        response = self._get(f"{ODDS_API_BASE}/{sport}/odds", UpstreamCallKind.SPORT, sport)
        quota, observation_id = self._read_quota(response, UpstreamCallKind.SPORT, sport)
        body = _checked_json(response, observation_id)
        return cast(list[dict[str, Any]], body), quota, observation_id

    def _fetch_event_odds(
        self, sport: str, event_id: str
    ) -> tuple[ProviderPayload, UpstreamQuota, int | None]:
        """GET /v4/sports/{sport}/events/{eventId}/odds from The Odds API.

        Costs [markets returned] x [regions], independent of how many events the
        sport has. A 404 means upstream no longer offers the event (finished or
        pulled), which is an empty answer rather than a failure.
        """
        response = self._get(
            f"{ODDS_API_BASE}/{sport}/events/{event_id}/odds",
            UpstreamCallKind.EVENT,
            sport,
            event_id=event_id,
        )
        quota, observation_id = self._read_quota(
            response, UpstreamCallKind.EVENT, sport, event_id=event_id
        )
        if response.status_code == 404:
            logger.info(
                "odds_api.event_not_offered",
                extra={"sport": sport, "event_id": event_id},
            )
            return [], quota, observation_id
        body = _checked_json(response, observation_id)
        return [cast(dict[str, Any], body)], quota, observation_id

    def check_quota(self) -> None:
        """GET /v4/sports: free, and it still carries the quota headers.

        How a paused Auto-Refresh learns that credits are back (ADR-016).
        """
        response = self._send(
            ODDS_API_BASE, {"apiKey": self._api_key}, UpstreamCallKind.BALANCE_CHECK, None
        )
        self._read_quota(response, UpstreamCallKind.BALANCE_CHECK, sport=None, cost=0)
        _raise_for_status(response)

    def _get(
        self,
        url: str,
        kind: UpstreamCallKind,
        sport: str,
        event_id: str | None = None,
    ) -> httpx.Response:
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
        return self._send(url, params, kind, sport, event_id)

    def _send(
        self,
        url: str,
        params: dict[str, str],
        kind: UpstreamCallKind,
        sport: str | None,
        event_id: str | None = None,
    ) -> httpx.Response:
        """Make one upstream call. A call that fails before any response (network
        error or timeout) is still a call: it is recorded, then the error is raised."""
        try:
            return self._client.get(url, params=params)
        except httpx.TransportError as error:
            observation_id = self._record_quota(
                QuotaReading(
                    kind=kind,
                    sport_key=sport,
                    event_id=event_id,
                    # No response, so no headers; nothing is assumed spent.
                    credits_spent=0,
                    estimated_cost=0,
                    outcome=UpstreamCallOutcome.NETWORK_ERROR,
                    observed_at=datetime.now(UTC),
                )
            )
            link_observation(error, observation_id)
            raise

    def _read_quota(
        self,
        response: httpx.Response,
        kind: UpstreamCallKind,
        sport: str | None,
        event_id: str | None = None,
        cost: int | None = None,
    ) -> tuple[UpstreamQuota, int | None]:
        """Read the quota off a response. Callers do this before raising on it:
        a rejected call is still a call, and what it cost is exactly what an
        operator needs to know when upstream starts failing.

        Returns the recorded observation's id too: None when nothing was stored."""
        quota = _parse_quota(response.headers)
        observation_id = self._record_quota(
            QuotaReading(
                kind=kind,
                sport_key=sport,
                event_id=event_id,
                credits_remaining=quota.credits_remaining,
                # A free endpoint spends nothing, whatever its cost header repeats.
                credits_spent=0 if cost == 0 else quota.credits_spent,
                credits_used=_parse_credit_header(response.headers.get("x-requests-used")),
                estimated_cost=self._call_cost if cost is None else cost,
                out_of_credits=_is_out_of_credits(response),
                outcome=_call_outcome(response),
                observed_at=datetime.now(UTC),
            )
        )
        logger.info(
            "odds_api.quota",
            extra={
                "sport": sport,
                "credits_spent": quota.credits_spent,
                "credits_remaining": quota.credits_remaining,
            },
        )
        return quota, observation_id

    def _record_quota(self, reading: QuotaReading) -> int | None:
        if self._quota_recorder is None:
            return None
        try:
            return self._quota_recorder.record(reading)
        except Exception:
            # Bookkeeping must never fail the refresh that paid for it.
            logger.exception("odds_api.quota_record_failed")
            return None

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
