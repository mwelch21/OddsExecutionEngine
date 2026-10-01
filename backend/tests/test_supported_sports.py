import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.quote_ingestion_service import (
    QuoteIngestionService,
    UnsupportedSportError,
)
from backend.app.config import Settings
from backend.app.domain.models import ProviderFetchReport, Quote, SupportedSport
from backend.app.engines.normalization_engine import NormalizationEngine
from backend.app.infrastructure.caching.in_process_cache import InProcessProviderCache
from backend.app.infrastructure.odds_api_provider import (
    SPORT_LEAGUE_MAP,
    TheOddsApiProvider,
)
from backend.app.infrastructure.publishers.in_memory_publisher import (
    InMemoryWorkflowEventPublisher,
)
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database


class CountingQuoteProvider:
    """Provider that records every fetch, so a test can assert none happened."""

    def __init__(self, supported: list[SupportedSport]) -> None:
        self._supported = supported
        self.sport_fetches: list[str] = []
        self.event_fetches: list[str] = []

    def list_quotes(self, event_id: str) -> list[Quote]:
        self.event_fetches.append(event_id)
        return []

    def list_quotes_for_sport(
        self, sport: str
    ) -> tuple[dict[str, list[Quote]], ProviderFetchReport]:
        self.sport_fetches.append(sport)
        return {}, ProviderFetchReport(upstream_contacted=True, data_age_seconds=0.0)

    def get_event_info(self, event_id: str) -> None:
        return None

    def list_supported_sports(self) -> list[SupportedSport]:
        return list(self._supported)


def _build_service(provider: CountingQuoteProvider) -> QuoteIngestionService:
    return QuoteIngestionService(
        unit_of_work_factory=lambda: pytest.fail("unit of work should not be reached"),
        quote_provider=provider,
        normalization_engine=NormalizationEngine(),
        workflow_event_publisher=InMemoryWorkflowEventPublisher(),
    )


def _supported() -> list[SupportedSport]:
    return [
        SupportedSport(key="americanfootball_nfl", sport="american_football", league="NFL"),
        SupportedSport(key="baseball_mlb", sport="baseball", league="MLB"),
    ]


def test_odds_api_catalog_is_read_from_the_single_sport_map() -> None:
    provider = TheOddsApiProvider(
        api_key="unused",
        sports=["americanfootball_nfl"],
        regions=["us"],
        markets=["h2h"],
        response_cache=InProcessProviderCache(ttl_seconds=0),
    )

    catalog = provider.list_supported_sports()

    assert {entry.key for entry in catalog} == set(SPORT_LEAGUE_MAP)
    nfl = next(entry for entry in catalog if entry.key == "americanfootball_nfl")
    assert (nfl.sport, nfl.league) == ("american_football", "NFL")


def test_catalog_is_not_narrowed_to_the_configured_sports() -> None:
    """ODDS_API_SPORTS bounds the per-event loop; it is not a whitelist."""
    provider = TheOddsApiProvider(
        api_key="unused",
        sports=["americanfootball_nfl"],
        regions=["us"],
        markets=["h2h"],
        response_cache=InProcessProviderCache(ttl_seconds=0),
    )

    keys = {entry.key for entry in provider.list_supported_sports()}

    assert "baseball_mlb" in keys
    assert len(keys) > 1


def test_unsupported_sport_is_rejected_before_any_upstream_call() -> None:
    provider = CountingQuoteProvider(_supported())
    service = _build_service(provider)

    with pytest.raises(UnsupportedSportError) as excinfo:
        service.refresh_sport("americanfootbal_nfl")

    assert provider.sport_fetches == []
    assert "americanfootball_nfl" in excinfo.value.supported


def test_supported_sport_outside_the_configured_list_still_refreshes() -> None:
    provider = CountingQuoteProvider(_supported())
    service = _build_service(provider)

    result = service.refresh_sport("baseball_mlb")

    assert result.sport == "baseball_mlb"
    assert result.summaries == []
    assert provider.sport_fetches == ["baseball_mlb"]


def test_sports_endpoint_lists_the_catalog(sqlite_database_url: str) -> None:
    with TestClient(_build_test_app(sqlite_database_url)) as client:
        response = client.get("/sports")

    assert response.status_code == 200
    sports = response.json()["sports"]
    assert sports
    assert all({"key", "sport", "league"} <= set(entry) for entry in sports)


def test_refresh_sport_rejects_an_unknown_key_with_422(sqlite_database_url: str) -> None:
    with TestClient(_build_test_app(sqlite_database_url)) as client:
        supported = [entry["key"] for entry in client.get("/sports").json()["sports"]]
        response = client.post(
            "/ingestion/quotes/refresh-sport",
            json={"sport": "not_a_real_sport"},
        )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "not_a_real_sport" in detail
    for key in supported:
        assert key in detail


def _build_test_app(database_url: str) -> FastAPI:
    prepare_test_database(database_url, seed_demo=True)
    settings = Settings(database_url_override=database_url, quote_provider="in_memory")
    return create_app(settings)
