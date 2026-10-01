"""What a refresh cost, and whether it actually went upstream.

Quota is billed in credits, not requests: one call costs
[markets] x [regions]. These tests pin that the figures reach the caller, and
that a reused response never reports figures it did not earn.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.infrastructure.caching.in_process_cache import InProcessProviderCache
from backend.app.infrastructure.odds_api_provider import TheOddsApiProvider
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database

SPORT = "icehockey_nhl"

EVENT: dict[str, Any] = {
    "id": "evt-1",
    "sport_key": SPORT,
    "commence_time": "2026-04-20T23:00:00Z",
    "home_team": "Home",
    "away_team": "Away",
    "bookmakers": [],
}


def _provider(cache_ttl_seconds: int = 300) -> TheOddsApiProvider:
    return TheOddsApiProvider(
        api_key="test-key",
        sports=[SPORT],
        regions=["us"],
        markets=["h2h", "spreads", "totals"],
        response_cache=InProcessProviderCache(ttl_seconds=cache_ttl_seconds),
    )


def _response(headers: dict[str, str]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = [EVENT]
    resp.headers = headers
    resp.raise_for_status = MagicMock()
    return resp


class TestQuotaParsing:
    def test_reads_the_cost_of_this_call_and_the_balance(self) -> None:
        provider = _provider()
        headers = {
            "x-requests-last": "3",
            "x-requests-remaining": "487",
            "x-requests-used": "13",
        }

        with patch.object(provider._client, "get", return_value=_response(headers)):
            _, quota = provider._fetch_sport_odds(SPORT)

        assert quota.credits_spent == 3
        assert quota.credits_remaining == 487

    def test_missing_headers_read_as_unreported_not_zero(self) -> None:
        """A call that appears to have cost nothing is a claim we cannot make."""
        provider = _provider()

        with patch.object(provider._client, "get", return_value=_response({})):
            _, quota = provider._fetch_sport_odds(SPORT)

        assert quota.credits_spent is None
        assert quota.credits_remaining is None

    def test_unparsable_headers_read_as_unreported(self) -> None:
        provider = _provider()
        headers = {"x-requests-last": "?", "x-requests-remaining": ""}

        with patch.object(provider._client, "get", return_value=_response(headers)):
            _, quota = provider._fetch_sport_odds(SPORT)

        assert quota.credits_spent is None
        assert quota.credits_remaining is None

    def test_quota_is_read_before_the_response_is_raised_on(self) -> None:
        """An error response still cost credits, so read them before raising."""
        provider = _provider()
        order: list[str] = []

        class RecordingHeaders:
            """Records that the quota was read, without being a dict subclass."""

            def __init__(self, values: dict[str, str]) -> None:
                self._values = values

            def get(self, key: str, default: str | None = None) -> str | None:
                order.append("headers")
                return self._values.get(key, default)

        resp = _response({})
        resp.headers = RecordingHeaders({"x-requests-last": "3", "x-requests-remaining": "0"})
        resp.raise_for_status = MagicMock(side_effect=lambda: order.append("raise"))

        with patch.object(provider._client, "get", return_value=resp):
            provider._fetch_sport_odds(SPORT)

        assert order.index("headers") < order.index("raise")


class TestFetchReport:
    def test_a_refresh_reports_the_credits_it_spent(self) -> None:
        provider = _provider()
        headers = {"x-requests-last": "3", "x-requests-remaining": "487"}

        with patch.object(provider._client, "get", return_value=_response(headers)):
            _, report = provider.list_quotes_for_sport(SPORT)

        assert report.upstream_contacted is True
        assert report.data_age_seconds == 0.0
        assert report.quota is not None
        assert report.quota.credits_spent == 3

    def test_a_refresh_always_pulls_live_even_inside_the_cache_window(self) -> None:
        """A deliberate refresh is never answered from the cache."""
        provider = _provider(cache_ttl_seconds=300)
        headers = {"x-requests-last": "3", "x-requests-remaining": "487"}

        with patch.object(
            provider._client, "get", return_value=_response(headers)
        ) as http_get:
            provider.list_quotes_for_sport(SPORT)
            _, second = provider.list_quotes_for_sport(SPORT)

        assert http_get.call_count == 2
        assert second.upstream_contacted is True

    def test_an_incidental_scan_reuses_the_response_within_the_ttl(self) -> None:
        """list_quotes walks every configured sport; the repeat is free."""
        provider = _provider(cache_ttl_seconds=300)
        headers = {"x-requests-last": "3", "x-requests-remaining": "487"}

        with patch.object(
            provider._client, "get", return_value=_response(headers)
        ) as http_get:
            provider.list_quotes("evt-1")
            provider.list_quotes("evt-1")

        assert http_get.call_count == 1


class TestRefreshEndpointReporting:
    def test_refresh_response_carries_the_cost_and_contact_flag(
        self, sqlite_database_url: str
    ) -> None:
        with TestClient(_build_app(sqlite_database_url)) as client:
            response = client.post(
                "/ingestion/quotes/refresh-sport",
                json={"sport": "basketball"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["sport"] == "basketball"
        assert set(body) >= {
            "upstream_contacted",
            "data_age_seconds",
            "credits_spent",
            "credits_remaining",
        }
        # The in-memory provider has no upstream, so there is nothing to bill.
        assert body["upstream_contacted"] is True
        assert body["credits_spent"] is None


def _build_app(database_url: str) -> FastAPI:
    prepare_test_database(database_url, seed_demo=True)
    settings = Settings(database_url_override=database_url, quote_provider="in_memory")
    return create_app(settings)
