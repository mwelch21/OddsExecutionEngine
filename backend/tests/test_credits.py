"""The Credits tab (#104): what each upstream call cost, the balance over time, burn.

Each test runs on SQLite and on migrated Postgres; the Postgres leg skips when no
integration database is configured.
"""

import os
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.application.quota_service import QuotaService
from backend.app.application.quote_ingestion_service import QuoteIngestionService
from backend.app.config import Settings
from backend.app.domain.models import ProviderFetchReport, Quote
from backend.app.domain.quota import (
    OutOfUsageCreditsError,
    QuotaReading,
    UpstreamCallKind,
    link_observation,
)
from backend.app.engines.normalization_engine import NormalizationEngine
from backend.app.engines.quota_engine import QuotaEngine
from backend.app.infrastructure.caching.in_process_cache import InProcessProviderCache
from backend.app.infrastructure.odds_api_provider import TheOddsApiProvider
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.quota_uow import SqlAlchemyQuotaUnitOfWork
from backend.app.infrastructure.persistence.quote_ingestion_uow import (
    SqlAlchemyQuoteIngestionUnitOfWork,
)
from backend.app.infrastructure.persistence.refresh_records import SqlAlchemyRefreshRecorder
from backend.app.infrastructure.publishers.in_memory_publisher import (
    InMemoryWorkflowEventPublisher,
)
from backend.app.infrastructure.quote_provider import (
    FIXTURE_EVENT_ID,
    InMemoryQuoteProvider,
    build_fixture_quotes,
)
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database
from backend.tests.test_auto_refresh import FIXTURE_SPORT_KEY

OCTOBER = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture(params=["sqlite", "postgres"])
def database_url(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    if request.param == "sqlite":
        return f"sqlite+pysqlite:///{tmp_path / 'test.db'}"
    url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Postgres integration environment is not configured.")
    return url


@pytest.fixture
def session_factory(database_url: str) -> Iterator[DatabaseSessionFactory]:
    factory = prepare_test_database(
        database_url, seed_demo=True, drop_existing=database_url.startswith("postgresql")
    )
    yield factory
    factory.engine.dispose()


@pytest.fixture
def quota(session_factory: DatabaseSessionFactory) -> QuotaService:
    return QuotaService(
        unit_of_work_factory=lambda: SqlAlchemyQuotaUnitOfWork(session_factory),
        quota_engine=QuotaEngine(),
    )


@pytest.fixture
def client(database_url: str, session_factory: DatabaseSessionFactory) -> TestClient:
    return TestClient(create_app(Settings(database_url_override=database_url)))


def _get(client: TestClient, path: str, **params: str | int) -> dict[str, Any]:
    response = client.get(f"/api/v1/admin/{path}", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _call(
    quota: QuotaService,
    at: datetime,
    *,
    kind: UpstreamCallKind = UpstreamCallKind.SPORT,
    sport: str | None = FIXTURE_SPORT_KEY,
    event_id: str | None = None,
    remaining: int | None = None,
    spent: int | None = 3,
) -> int:
    """Record one upstream call as the provider would, and return its observation id."""
    return quota.record(
        QuotaReading(
            kind=kind,
            sport_key=sport,
            event_id=event_id,
            credits_remaining=remaining,
            credits_used=None if remaining is None else 500 - remaining,
            credits_spent=spent,
            estimated_cost=3,
            observed_at=at,
        )
    )


def _report(observation_id: int | None) -> ProviderFetchReport:
    return ProviderFetchReport(
        upstream_contacted=True, data_age_seconds=0.0, observation_id=observation_id
    )


def _fixture_sport_quotes() -> dict[str, list[Quote]]:
    return {FIXTURE_EVENT_ID: build_fixture_quotes()}


# --- the refresh log shows each refresh's cost through its linked call ---


def test_a_refresh_links_to_its_call_and_the_log_shows_its_cost(
    client: TestClient, quota: QuotaService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def pull(self: object, sport: str) -> tuple[dict[str, list[Quote]], ProviderFetchReport]:
        observation_id = _call(quota, datetime.now(UTC), remaining=497, spent=3)
        return _fixture_sport_quotes(), _report(observation_id)

    monkeypatch.setattr(InMemoryQuoteProvider, "list_quotes_for_sport", pull)

    response = client.post(
        "/api/v1/ingestion/quotes/refresh-sport", json={"sport": FIXTURE_SPORT_KEY}
    )

    assert response.status_code == 200
    [row] = _get(client, "refreshes")["refreshes"]
    assert (row["outcome"], row["credits_spent"]) == ("succeeded", 3)


def test_a_refresh_that_failed_after_its_call_still_shows_the_cost(
    client: TestClient, quota: QuotaService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: object, event_id: str, sport: str) -> object:
        error = OutOfUsageCreditsError()
        call = _call(
            quota, datetime.now(UTC), kind=UpstreamCallKind.EVENT, event_id=event_id, spent=0
        )
        link_observation(error, call)
        raise error

    monkeypatch.setattr(InMemoryQuoteProvider, "list_quotes", refuse)

    response = client.post("/api/v1/ingestion/quotes/refresh", json={"event_id": FIXTURE_EVENT_ID})

    assert response.status_code == 503
    [row] = _get(client, "refreshes")["refreshes"]
    assert (row["outcome"], row["credits_spent"]) == ("refused", 0)


def test_a_refresh_that_failed_before_any_call_has_no_cost(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(self: object, sport: str) -> object:
        raise RuntimeError("connect timeout")

    monkeypatch.setattr(InMemoryQuoteProvider, "list_quotes_for_sport", unreachable)

    with pytest.raises(RuntimeError):
        client.post("/api/v1/ingestion/quotes/refresh-sport", json={"sport": FIXTURE_SPORT_KEY})

    [row] = _get(client, "refreshes")["refreshes"]
    assert (row["outcome"], row["credits_spent"]) == ("failed", None)


def test_coalesced_refreshes_share_one_call_and_burn_counts_it_once(
    client: TestClient, quota: QuotaService, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two refreshes served by one upstream call, as the provider cache coalesces them.
    shared = _call(quota, datetime.now(UTC), remaining=497, spent=3)

    def coalesced(self: object, sport: str) -> tuple[dict[str, list[Quote]], ProviderFetchReport]:
        return _fixture_sport_quotes(), _report(shared)

    monkeypatch.setattr(InMemoryQuoteProvider, "list_quotes_for_sport", coalesced)
    for _ in range(2):
        response = client.post(
            "/api/v1/ingestion/quotes/refresh-sport", json={"sport": FIXTURE_SPORT_KEY}
        )
        assert response.status_code == 200

    rows = _get(client, "refreshes")["refreshes"]
    assert [row["credits_spent"] for row in rows] == [3, 3]
    burn = _get(client, "credit-burn")
    assert (burn["total_credits"], burn["total_calls"]) == (3, 1)
    assert burn["by_sport"] == [{"sport": FIXTURE_SPORT_KEY, "credits": 3, "calls": 1}]


# --- quota history: the last remaining balance per hour ---


def test_history_and_burn_are_empty_before_any_call(client: TestClient) -> None:
    assert _get(client, "quota-history") == {"days": 30, "points": []}
    burn = _get(client, "credit-burn", month="2026-10")
    assert (burn["total_credits"], burn["total_calls"], burn["by_sport"], burn["by_kind"]) == (
        0,
        0,
        [],
        [],
    )
    auto = _get(client, "auto-refresh")
    assert (auto["out_of_credits"], auto["quota"]) == (False, None)


def test_history_keeps_the_last_balance_of_each_hour_within_the_window(
    client: TestClient, quota: QuotaService
) -> None:
    this_hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    _call(quota, this_hour - timedelta(days=31), remaining=500)  # outside 30 days
    _call(quota, this_hour - timedelta(hours=2, minutes=-5), remaining=480)
    _call(quota, this_hour - timedelta(hours=2, minutes=-40), remaining=477)  # same hour, later
    # No headers: the local count carries the balance forward, 477 - 3.
    _call(quota, this_hour - timedelta(hours=1, minutes=-10), remaining=None)
    _call(quota, this_hour, remaining=470)

    points = _get(client, "quota-history")["points"]

    assert [(datetime.fromisoformat(p["hour"]), p["remaining"]) for p in points] == [
        (this_hour - timedelta(hours=2), 477),
        (this_hour - timedelta(hours=1), 474),
        (this_hour, 470),
    ]
    assert _get(client, "quota-history", days=1)["points"][-1]["remaining"] == 470


def test_history_days_is_bounded(client: TestClient) -> None:
    for days in (0, 31):
        assert client.get("/api/v1/admin/quota-history", params={"days": days}).status_code == 422


# --- credit burn: per sport and per call kind, one seeded month ---


def test_burn_totals_a_seeded_month_per_sport_and_kind(
    client: TestClient, quota: QuotaService
) -> None:
    _call(quota, OCTOBER - timedelta(seconds=1), spent=3)  # September: not counted
    _call(quota, OCTOBER, spent=3)
    _call(quota, OCTOBER + timedelta(days=3), spent=3)
    _call(
        quota,
        OCTOBER + timedelta(days=4),
        kind=UpstreamCallKind.EVENT,
        event_id=FIXTURE_EVENT_ID,
        spent=2,
    )
    _call(quota, OCTOBER + timedelta(days=5), sport="icehockey_nhl", spent=3)
    _call(
        quota,
        OCTOBER + timedelta(days=6),
        kind=UpstreamCallKind.BALANCE_CHECK,
        sport=None,
        remaining=0,
        spent=0,
    )
    _call(quota, OCTOBER + timedelta(days=31), spent=3)  # November: not counted

    burn = _get(client, "credit-burn", month="2026-10")

    assert (burn["month"], burn["total_credits"], burn["total_calls"]) == ("2026-10", 11, 5)
    assert datetime.fromisoformat(burn["starts_at"]) == OCTOBER
    assert datetime.fromisoformat(burn["ends_at"]) == datetime(2026, 11, 1, tzinfo=UTC)
    assert burn["by_sport"] == [
        {"sport": FIXTURE_SPORT_KEY, "credits": 8, "calls": 3},
        {"sport": "icehockey_nhl", "credits": 3, "calls": 1},
    ]
    assert burn["by_kind"] == [
        {"kind": "sport", "credits": 9, "calls": 3},
        {"kind": "event", "credits": 2, "calls": 1},
        {"kind": "balance_check", "credits": 0, "calls": 1},
    ]


def test_burn_month_must_be_yyyy_mm(client: TestClient) -> None:
    for month in ("2026-13", "2026-1", "october"):
        assert client.get("/api/v1/admin/credit-burn", params={"month": month}).status_code == 422


def test_auto_refresh_reports_out_of_credits(client: TestClient, quota: QuotaService) -> None:
    quota.record(
        QuotaReading(
            kind=UpstreamCallKind.SPORT,
            sport_key=FIXTURE_SPORT_KEY,
            out_of_credits=True,
            estimated_cost=3,
            observed_at=datetime.now(UTC),
        )
    )

    auto = _get(client, "auto-refresh")

    assert (auto["out_of_credits"], auto["paused"]) == (True, True)


def test_a_paused_balance_check_keeps_out_of_credits_while_none_are_left(
    client: TestClient, quota: QuotaService
) -> None:
    now = datetime.now(UTC)
    quota.record(
        QuotaReading(
            kind=UpstreamCallKind.SPORT,
            sport_key=FIXTURE_SPORT_KEY,
            out_of_credits=True,
            estimated_cost=3,
            observed_at=now,
        )
    )
    # The free balance check answers 200 with 0 left: not a refusal, still no credits.
    _call(
        quota,
        now + timedelta(minutes=5),
        kind=UpstreamCallKind.BALANCE_CHECK,
        sport=None,
        remaining=0,
        spent=0,
    )

    auto = _get(client, "auto-refresh")

    assert (auto["out_of_credits"], auto["paused"]) == (True, True)


def test_two_refreshes_coalesced_by_the_real_cache_link_one_stored_call(
    client: TestClient, session_factory: DatabaseSessionFactory, quota: QuotaService
) -> None:
    """End to end on storage: provider cache, quota record, refresh records, burn."""
    provider = TheOddsApiProvider(
        api_key="test-key",
        regions=["us"],
        markets=["h2h", "spreads", "totals"],
        response_cache=InProcessProviderCache(ttl_seconds=0),
        quota_recorder=quota,
    )
    ingestion = QuoteIngestionService(
        unit_of_work_factory=lambda: SqlAlchemyQuoteIngestionUnitOfWork(session_factory),
        quote_provider=provider,
        normalization_engine=NormalizationEngine(),
        workflow_event_publisher=InMemoryWorkflowEventPublisher(),
        refresh_recorder=SqlAlchemyRefreshRecorder(session_factory),
    )
    entered = threading.Event()
    release = threading.Event()

    def slow_get(*_: Any, **__: Any) -> httpx.Response:
        entered.set()
        assert release.wait(timeout=5), "upstream call was never released"
        return httpx.Response(
            200,
            json=[],
            headers={"x-requests-remaining": "497", "x-requests-used": "3", "x-requests-last": "3"},
            request=httpx.Request("GET", "https://api.the-odds-api.com/v4/sports"),
        )

    with patch.object(provider._client, "get", side_effect=slow_get):
        first = threading.Thread(target=ingestion.refresh_sport, args=("icehockey_nhl",))
        first.start()
        assert entered.wait(timeout=5), "first call never started"
        second = threading.Thread(target=ingestion.refresh_sport, args=("icehockey_nhl",))
        second.start()
        time.sleep(0.1)  # let the second refresh queue behind the call in flight
        release.set()
        for thread in (first, second):
            thread.join(timeout=10)
            assert not thread.is_alive()

    rows = _get(client, "refreshes")["refreshes"]
    assert [(row["sport"], row["credits_spent"]) for row in rows] == [
        ("icehockey_nhl", 3),
        ("icehockey_nhl", 3),
    ]
    burn = _get(client, "credit-burn")
    assert (burn["total_credits"], burn["total_calls"]) == (3, 1)
