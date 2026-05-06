from unittest.mock import MagicMock, patch

import pytest

from backend.app.domain.models import MarketType
from backend.app.infrastructure.odds_api_provider import TheOddsApiProvider

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


def _make_mock_response(json_data: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.headers = {
        "x-requests-remaining": "490",
        "x-requests-used": "10",
    }
    resp.raise_for_status = MagicMock()
    return resp


def _create_provider() -> TheOddsApiProvider:
    return TheOddsApiProvider(
        api_key="test-key",
        sports=["icehockey_nhl"],
        regions=["us", "us2"],
        markets=["h2h", "spreads", "totals"],
    )


class TestListQuotes:
    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_API_RESPONSE)
    def test_returns_quotes_for_matching_event(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes = provider.list_quotes("abc123")

        assert len(quotes) > 0
        assert all(q.event_id == "abc123" for q in quotes)

    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_API_RESPONSE)
    def test_returns_empty_for_unknown_event(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes = provider.list_quotes("nonexistent")

        assert quotes == []

    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_API_RESPONSE)
    def test_maps_h2h_to_moneyline(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes = provider.list_quotes("abc123")

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

    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_API_RESPONSE)
    def test_maps_spreads_with_line(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes = provider.list_quotes("abc123")

        spread_quotes = [q for q in quotes if q.market_type == MarketType.SPREAD]
        assert len(spread_quotes) == 2
        assert all(q.line is not None for q in spread_quotes)

        bruins_spread = [q for q in spread_quotes if "bruins" in q.selection]
        assert len(bruins_spread) == 1
        assert bruins_spread[0].line == -1.5
        assert bruins_spread[0].price == -110

    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_API_RESPONSE)
    def test_maps_totals_with_over_under(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes = provider.list_quotes("abc123")

        total_quotes = [q for q in quotes if q.market_type == MarketType.TOTAL]
        assert len(total_quotes) == 2
        selections = {q.selection for q in total_quotes}
        assert selections == {"over", "under"}
        assert all(q.line == 5.5 for q in total_quotes)

    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_API_RESPONSE)
    def test_multiple_sportsbooks(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes = provider.list_quotes("abc123")

        sportsbooks = {q.sportsbook for q in quotes}
        assert "draftkings" in sportsbooks
        assert "fanduel" in sportsbooks


class TestListEventsForSport:
    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_API_RESPONSE)
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

    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_API_RESPONSE)
    def test_caches_event_info(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        provider.list_events_for_sport("icehockey_nhl")

        info = provider.get_event_info("abc123")
        assert info is not None
        assert info.participants[0].name == "Boston Bruins"


class TestListQuotesForSport:
    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_API_RESPONSE)
    def test_returns_dict_of_event_quotes(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        result = provider.list_quotes_for_sport("icehockey_nhl")

        assert "abc123" in result
        assert "def456" in result
        assert len(result["abc123"]) > 0
        assert len(result["def456"]) > 0

    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=SAMPLE_API_RESPONSE)
    def test_single_api_call(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        provider.list_quotes_for_sport("icehockey_nhl")

        mock_fetch.assert_called_once_with("icehockey_nhl")


class TestEdgeCases:
    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=[])
    def test_empty_response(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes = provider.list_quotes("abc123")
        assert quotes == []

    @patch.object(TheOddsApiProvider, "_fetch_sport_odds", return_value=[
        {
            "id": "evt1",
            "commence_time": "2026-04-20T23:00:00Z",
            "home_team": "A",
            "away_team": "B",
            "bookmakers": [],
        }
    ])
    def test_event_with_no_bookmakers(self, mock_fetch: MagicMock) -> None:
        provider = _create_provider()
        quotes = provider.list_quotes("evt1")
        assert quotes == []

    @patch.object(TheOddsApiProvider, "_fetch_sport_odds")
    def test_api_error_propagates(self, mock_fetch: MagicMock) -> None:
        mock_fetch.side_effect = Exception("API error")
        provider = _create_provider()
        with pytest.raises(Exception, match="API error"):
            provider.list_quotes("abc123")
