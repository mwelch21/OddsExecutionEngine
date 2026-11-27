import json
from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.app.domain.models import MarketType, Quote, UpstreamQuota
from backend.app.infrastructure.caching.in_process_cache import InProcessProviderCache
from backend.app.infrastructure.odds_api_provider import TheOddsApiProvider

# The fetch helpers return (payload, quota); these tests are about the mapping,
# so they hand back an unreported quota.
NO_QUOTA = UpstreamQuota()

SAMPLE_API_RESPONSE = [
    {
        "id": "abc123",
        "sport_key": "icehockey_nhl",
        "commence_time": "2026-04-20T23:00:00Z",
        "home_team": "Boston Bruins",
        "away_team": "New York Rangers",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Boston Bruins", "price": -145},
                            {"name": "New York Rangers", "price": 125},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Boston Bruins", "price": -110, "point": -1.5},
                            {"name": "New York Rangers", "price": -110, "point": 1.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -112, "point": 5.5},
                            {"name": "Under", "price": -108, "point": 5.5},
                        ],
                    },
                ],
            },
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Boston Bruins", "price": -140},
                            {"name": "New York Rangers", "price": 120},
                        ],
                    },
                ],
            },
        ],
    },
    {
        "id": "def456",
        "sport_key": "icehockey_nhl",
        "commence_time": "2026-04-21T00:00:00Z",
        "home_team": "Toronto Maple Leafs",
        "away_team": "Montreal Canadiens",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Toronto Maple Leafs", "price": -180},
                            {"name": "Montreal Canadiens", "price": 155},
                        ],
                    },
                ],
            },
        ],
    },
]

SAMPLE_FETCH = (SAMPLE_API_RESPONSE, NO_QUOTA, None)
EMPTY_FETCH: tuple[list[dict], UpstreamQuota, int | None] = ([], NO_QUOTA, None)
SPORT_KEY = "icehockey_nhl"


def _serve_events(
    response: list[dict],
) -> Callable[[str, str], tuple[list[dict], UpstreamQuota, int | None]]:
    """Stand in for the single-event endpoint: answer with just the named event."""

    def fetch(sport: str, event_id: str) -> tuple[list[dict], UpstreamQuota, int | None]:
        return [event for event in response if event["id"] == event_id], NO_QUOTA, None

    return fetch


def _make_mock_response(json_data: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.headers = {
        "x-requests-remaining": "490",
        "x-requests-used": "10",
    }
    resp.raise_for_status = MagicMock()
    return resp


def _create_provider(ttl_seconds: int = 0) -> TheOddsApiProvider:
    # TTL 0 by default so each test's upstream call count is its own doing and
    # not an artefact of reuse between calls within the test.
    return TheOddsApiProvider(
        api_key="test-key",
        regions=["us", "us2"],
        markets=["h2h", "spreads", "totals"],
        response_cache=InProcessProviderCache(ttl_seconds=ttl_seconds),
    )


class TestListQuotes:
    @patch.object(
        TheOddsApiProvider, "_fetch_event_odds", side_effect=_serve_events(SAMPLE_API_RESPONSE)
    )
    def test_returns_quotes_for_matching_event(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes, _ = provider.list_quotes("abc123", SPORT_KEY)

        assert len(quotes) > 0
        assert all(q.event_id == "abc123" for q in quotes)

    @patch.object(
        TheOddsApiProvider, "_fetch_event_odds", side_effect=_serve_events(SAMPLE_API_RESPONSE)
    )
    def test_returns_empty_for_unknown_event(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes, report = provider.list_quotes("nonexistent", SPORT_KEY)

        assert quotes == []
        # A 404 is an empty answer: upstream no longer offers the event (#38).
        assert report.event_offered is False

    @patch.object(
        TheOddsApiProvider, "_fetch_event_odds", side_effect=_serve_events(SAMPLE_API_RESPONSE)
    )
    def test_reports_an_answered_event_as_offered(self, mock_fetch: MagicMock) -> None:
        _, report = _create_provider().list_quotes("abc123", SPORT_KEY)

        assert report.event_offered is True

    @patch.object(
        TheOddsApiProvider, "_fetch_event_odds", side_effect=_serve_events(SAMPLE_API_RESPONSE)
    )
    def test_maps_h2h_to_moneyline(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes, _ = provider.list_quotes("abc123", SPORT_KEY)

        ml_quotes = [q for q in quotes if q.market_type == MarketType.MONEYLINE]
        assert len(ml_quotes) >= 2
        assert all(q.line is None for q in ml_quotes)

        dk_bruins = [
            q
            for q in ml_quotes
            if q.sportsbook == "draftkings" and "bruins" in q.selection
        ]
        assert len(dk_bruins) == 1
        assert dk_bruins[0].price == -145

    @patch.object(
        TheOddsApiProvider, "_fetch_event_odds", side_effect=_serve_events(SAMPLE_API_RESPONSE)
    )
    def test_maps_spreads_with_line(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes, _ = provider.list_quotes("abc123", SPORT_KEY)

        spread_quotes = [q for q in quotes if q.market_type == MarketType.SPREAD]
        assert len(spread_quotes) == 2
        assert all(q.line is not None for q in spread_quotes)

        bruins_spread = [q for q in spread_quotes if "bruins" in q.selection]
        assert len(bruins_spread) == 1
        assert bruins_spread[0].line == -1.5
        assert bruins_spread[0].price == -110

    @patch.object(
        TheOddsApiProvider, "_fetch_event_odds", side_effect=_serve_events(SAMPLE_API_RESPONSE)
    )
    def test_maps_totals_with_over_under(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes, _ = provider.list_quotes("abc123", SPORT_KEY)

        total_quotes = [q for q in quotes if q.market_type == MarketType.TOTAL]
        assert len(total_quotes) == 2
        selections = {q.selection for q in total_quotes}
        assert selections == {"over", "under"}
        assert all(q.line == 5.5 for q in total_quotes)

    @patch.object(
        TheOddsApiProvider, "_fetch_event_odds", side_effect=_serve_events(SAMPLE_API_RESPONSE)
    )
    def test_multiple_sportsbooks(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes, _ = provider.list_quotes("abc123", SPORT_KEY)

        sportsbooks = {q.sportsbook for q in quotes}
        assert "draftkings" in sportsbooks
        assert "fanduel" in sportsbooks


class TestListEventsForSport:
    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_FETCH)
    def test_returns_event_info(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        events = provider.list_events_for_sport("icehockey_nhl")

        assert len(events) == 2
        assert events[0].id == "abc123"
        assert events[0].sport == "ice_hockey"
        assert events[0].league == "NHL"
        assert len(events[0].participants) == 2
        home = [p for p in events[0].participants if p.side == "home"]
        assert len(home) == 1
        assert home[0].name == "Boston Bruins"
        away = [p for p in events[0].participants if p.side == "away"]
        assert len(away) == 1
        assert away[0].name == "New York Rangers"

    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_FETCH)
    def test_caches_event_info(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        provider.list_events_for_sport("icehockey_nhl")

        info = provider.get_event_info("abc123")
        assert info is not None
        assert info.participants[0].name == "Boston Bruins"


class TestListQuotesForSport:
    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_FETCH)
    def test_returns_dict_of_event_quotes(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        result, _ = provider.list_quotes_for_sport("icehockey_nhl")

        assert "abc123" in result
        assert "def456" in result
        assert len(result["abc123"]) > 0
        assert len(result["def456"]) > 0

    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_FETCH)
    def test_single_api_call(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        provider.list_quotes_for_sport("icehockey_nhl")

        mock_fetch.assert_called_once_with("icehockey_nhl")


class TestEdgeCases:
    @patch.object(TheOddsApiProvider, "_fetch_event_odds", return_value=EMPTY_FETCH)
    def test_empty_response(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes, _ = provider.list_quotes("abc123", SPORT_KEY)
        assert quotes == []

    @patch.object(
        TheOddsApiProvider,
        "_fetch_event_odds",
        return_value=(
            [
                {
                    "id": "evt1",
                    "commence_time": "2026-04-20T23:00:00Z",
                    "home_team": "A",
                    "away_team": "B",
                    "bookmakers": [],
                }
            ],
            NO_QUOTA,
            None,
        ),
    )
    def test_event_with_no_bookmakers(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes, _ = provider.list_quotes("evt1", SPORT_KEY)
        assert quotes == []

    @patch.object(TheOddsApiProvider, "_fetch_event_odds")
    def test_api_error_propagates(self, mock_fetch: MagicMock) -> None:
        mock_fetch.side_effect = Exception("API error")
        provider = _create_provider()
        with pytest.raises(Exception, match="API error"):
            provider.list_quotes("abc123", SPORT_KEY)


LAST_UPDATE_RESPONSE = [
    {
        "id": "abc123",
        "sport_key": "icehockey_nhl",
        "commence_time": "2026-04-20T23:00:00Z",
        "home_team": "Boston Bruins",
        "away_team": "New York Rangers",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "2026-04-20T21:00:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "last_update": "2026-04-17T09:30:00Z",
                        "outcomes": [{"name": "Boston Bruins", "price": -145}],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Boston Bruins", "price": -110, "point": -1.5}
                        ],
                    },
                ],
            },
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [{"name": "Boston Bruins", "price": -140}],
                    },
                ],
            },
            {
                "key": "caesars",
                "title": "Caesars",
                # The Odds API reports UTC, but without an offset marker here.
                "last_update": "2026-04-17T09:30:00",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [{"name": "Boston Bruins", "price": -150}],
                    },
                ],
            },
        ],
    },
]

class TestLineMovementTime:
    @patch.object(
        TheOddsApiProvider, "_fetch_event_odds", side_effect=_serve_events(LAST_UPDATE_RESPONSE)
    )
    def test_market_last_update_becomes_the_books_quote_time(
        self, mock_fetch: MagicMock
    ) -> None:
        provider = _create_provider()
        quotes, _ = provider.list_quotes("abc123", SPORT_KEY)

        quote = _only(quotes, "draftkings", MarketType.MONEYLINE)
        assert quote.quoted_at == datetime(2026, 4, 17, 9, 30, tzinfo=UTC)
        assert quote.line_age_known is True

    @patch.object(
        TheOddsApiProvider, "_fetch_event_odds", side_effect=_serve_events(LAST_UPDATE_RESPONSE)
    )
    def test_falls_back_to_bookmaker_last_update_when_the_market_has_none(
        self, mock_fetch: MagicMock
    ) -> None:
        provider = _create_provider()
        quotes, _ = provider.list_quotes("abc123", SPORT_KEY)

        quote = _only(quotes, "draftkings", MarketType.SPREAD)
        assert quote.quoted_at == datetime(2026, 4, 20, 21, 0, tzinfo=UTC)

    @patch.object(
        TheOddsApiProvider, "_fetch_event_odds", side_effect=_serve_events(LAST_UPDATE_RESPONSE)
    )
    def test_offsetless_last_update_is_read_as_utc(self, mock_fetch: MagicMock) -> None:
        """A naive timestamp would land in a tz-aware column and shift by the
        server's offset — silently wrong on the one fact this data exists to state."""
        provider = _create_provider()
        quotes, _ = provider.list_quotes("abc123", SPORT_KEY)

        quote = _only(quotes, "caesars", MarketType.MONEYLINE)
        assert quote.quoted_at == datetime(2026, 4, 17, 9, 30, tzinfo=UTC)

    @patch.object(
        TheOddsApiProvider, "_fetch_event_odds", side_effect=_serve_events(LAST_UPDATE_RESPONSE)
    )
    def test_absent_last_update_leaves_the_quote_unknown_age(
        self, mock_fetch: MagicMock
    ) -> None:
        provider = _create_provider()
        quotes, _ = provider.list_quotes("abc123", SPORT_KEY)

        quote = _only(quotes, "fanduel", MarketType.MONEYLINE)
        assert quote.quoted_at is None
        assert quote.line_age_known is False


def _only(quotes: list[Quote], sportsbook: str, market_type: MarketType) -> Quote:
    matches = [
        q for q in quotes if q.sportsbook == sportsbook and q.market_type is market_type
    ]
    assert len(matches) == 1
    return matches[0]


class TestSingleEventAbsence:
    """A per-event 200 that names no event is absent; an event with no books is not (#38).

    Runs the real adapter over a stubbed HTTP client, so nothing reaches upstream.
    """

    @staticmethod
    def _provider_answering(body: object) -> tuple[TheOddsApiProvider, list[httpx.Request]]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            # `content`, not `json=`: httpx reads `json=None` as no body at all.
            return httpx.Response(
                200,
                content=json.dumps(body).encode(),
                headers={"content-type": "application/json", "x-requests-last": "3"},
            )

        provider = _create_provider()
        provider._client = httpx.Client(transport=httpx.MockTransport(handler))
        return provider, seen

    @pytest.mark.parametrize("body", [[], None])
    def test_an_empty_or_null_body_is_an_absent_event(self, body: object) -> None:
        provider, seen = self._provider_answering(body)

        quotes, report = provider.list_quotes("gone", SPORT_KEY)

        assert quotes == []
        assert report.event_offered is False
        assert len(seen) == 1
        assert seen[0].url.path.endswith("/events/gone/odds")

    def test_an_event_with_no_bookmakers_is_still_offered(self) -> None:
        event = {**SAMPLE_API_RESPONSE[0], "bookmakers": []}
        provider, seen = self._provider_answering(event)

        quotes, report = provider.list_quotes(str(event["id"]), SPORT_KEY)

        assert quotes == []
        assert report.event_offered is True
        assert len(seen) == 1
