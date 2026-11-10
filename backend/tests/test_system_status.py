import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, update

from backend.app.application.quota_service import QuotaService
from backend.app.application.system_status_query_service import SystemStatusQueryService
from backend.app.config import Settings
from backend.app.engines.component_status_engine import ComponentStatusEngine
from backend.app.engines.quota_engine import QuotaEngine
from backend.app.infrastructure.caching.in_process_cache import InProcessProviderCache
from backend.app.infrastructure.odds_api_provider import TheOddsApiProvider
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.quota_uow import SqlAlchemyQuotaUnitOfWork
from backend.app.infrastructure.persistence.schema import (
    auto_refresh_settings_table,
    deliveries_table,
    destinations_table,
    public_events_table,
    quota_observations_table,
    refresh_records_table,
)
from backend.app.infrastructure.persistence.system_status_read_uow import (
    NOTIFIER_LISTENER_APPLICATION_NAME,
    SqlAlchemySystemStatusReadUnitOfWork,
)
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def _database_urls() -> list[Any]:
    return [
        pytest.param("sqlite", id="sqlite"),
        pytest.param(
            os.environ.get("STAGE2_TEST_DATABASE_URL"),
            id="postgres",
            marks=pytest.mark.skipif(
                not os.environ.get("STAGE2_TEST_DATABASE_URL"),
                reason="Postgres integration environment is not configured.",
            ),
        ),
    ]


class Stack:
    """A migrated database, the app over it, and the service on a fixed clock."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.session_factory: DatabaseSessionFactory = prepare_test_database(
            database_url, seed_demo=False, drop_existing=not database_url.startswith("sqlite")
        )
        self.client = TestClient(create_app(Settings(database_url_override=database_url)))
        self.service = SystemStatusQueryService(
            unit_of_work_factory=lambda: SqlAlchemySystemStatusReadUnitOfWork(self.session_factory),
            component_status_engine=ComponentStatusEngine(),
            quota_engine=QuotaEngine(),
            clock=lambda: NOW,
        )
        self._ids = 0

    @property
    def is_postgres(self) -> bool:
        return not self.database_url.startswith("sqlite")

    def _insert(self, table: Any, **values: Any) -> None:
        with self.session_factory.create_session() as session:
            session.execute(insert(table).values(**values))
            session.commit()

    def refresh(
        self,
        outcome: str,
        minutes_ago: int,
        error_code: str | None = None,
        sport: str = "basketball_nba",
    ) -> None:
        finished_at = NOW - timedelta(minutes=minutes_ago)
        self._insert(
            refresh_records_table,
            scope="sport",
            sport_key=sport,
            event_id=None,
            trigger="manual",
            started_at=finished_at - timedelta(seconds=2),
            finished_at=finished_at,
            outcome=outcome,
            error_code=error_code,
            error=None if error_code is None else "detail",
            events_refreshed=3 if outcome == "succeeded" else 0,
        )

    def call(self, outcome: str | None, minutes_ago: int, kind: str = "sport") -> None:
        """One upstream call, as the provider records it; a None outcome is a row
        from before outcomes were kept."""
        self._insert(
            quota_observations_table,
            remaining=400,
            used=100,
            source="headers",
            out_of_credits=outcome == "out_of_credits",
            observed_at=NOW - timedelta(minutes=minutes_ago),
            call_kind=kind,
            credits_spent=0 if kind == "balance_check" else 3,
            call_outcome=outcome,
        )

    def provider(self) -> TheOddsApiProvider:
        """The real provider recording through the real quota store; tests patch
        its HTTP client, so nothing reaches upstream."""
        return TheOddsApiProvider(
            api_key="test-key",
            regions=["us"],
            markets=["h2h", "spreads", "totals"],
            response_cache=InProcessProviderCache(ttl_seconds=0),
            quota_recorder=QuotaService(
                unit_of_work_factory=lambda: SqlAlchemyQuotaUnitOfWork(self.session_factory),
                quota_engine=QuotaEngine(),
            ),
        )

    def quota(self, remaining: int, used: int, minutes_ago: int, out: bool = False) -> None:
        self._insert(
            quota_observations_table,
            remaining=remaining,
            used=used,
            source="headers",
            out_of_credits=out,
            observed_at=NOW - timedelta(minutes=minutes_ago),
        )

    def floor(self, value: int) -> None:
        with self.session_factory.create_session() as session:
            updated = session.execute(update(auto_refresh_settings_table).values(quota_floor=value))
            if updated.rowcount == 0:  # type: ignore[attr-defined]
                session.execute(insert(auto_refresh_settings_table).values(id=1, quota_floor=value))
            session.commit()

    def delivery(self, status: str, hours_ago: float) -> None:
        self._ids += 1
        if self._ids == 1:
            self._insert(
                destinations_table,
                id="dest-1",
                channel="web_push",
                label="iPhone",
                address="https://push.example/secret",
                config={"p256dh": "k", "auth": "a"},
            )
        event_id = f"evt-{self._ids}"
        self._insert(
            public_events_table,
            id=event_id,
            type="oddsengine.destination.test.v1",
            payload={"id": event_id, "data": {}},
        )
        self._insert(
            deliveries_table,
            id=f"d-{self._ids}",
            event_id=event_id,
            destination_id="dest-1",
            status=status,
            created_at=NOW - timedelta(hours=hours_ago),
        )


@pytest.fixture(params=_database_urls())
def stack(request: pytest.FixtureRequest, sqlite_database_url: str) -> Iterator[Stack]:
    url = sqlite_database_url if request.param == "sqlite" else request.param
    built = Stack(url)
    try:
        yield built
    finally:
        built.session_factory.engine.dispose()


def _states(stack: Stack) -> dict[str, str]:
    body = stack.client.get("/api/v1/admin/component-status").json()
    return {row["component"]: row["state"] for row in body["components"]}


def test_health_reports_the_database(stack: Stack) -> None:
    body = stack.client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["database"] == "healthy"


def test_an_unreachable_database_is_unhealthy_and_hides_the_other_signals(
    tmp_path: Any,
) -> None:
    url = f"sqlite:///{tmp_path}/missing-dir/odds.db"
    client = TestClient(create_app(Settings(database_url_override=url)))

    health = client.get("/api/health")
    status = client.get("/api/v1/admin/component-status")

    assert health.status_code == 200
    assert health.json()["database"] == "unhealthy"
    assert status.status_code == 200
    assert {row["component"]: row["state"] for row in status.json()["components"]} == {
        "database": "unhealthy",
        "notifier": "unknown",
        "provider": "unknown",
    }


def test_an_unreachable_postgres_is_unhealthy_too() -> None:
    # Nothing listens on port 1: the connect fails as it would with Postgres down.
    url = "postgresql+psycopg://app:app@127.0.0.1:1/odds_execution?connect_timeout=2"
    client = TestClient(create_app(Settings(database_url_override=url)))

    assert client.get("/api/health").json()["database"] == "unhealthy"
    assert [
        row["state"] for row in client.get("/api/v1/admin/component-status").json()["components"]
    ] == ["unhealthy", "unknown", "unknown"]


def test_with_nothing_stored_the_provider_is_unknown(stack: Stack) -> None:
    states = _states(stack)

    assert states["database"] == "healthy"
    assert states["provider"] == "unknown"
    # SQLite has no pg_stat_activity; Postgres has no listener in the test database.
    assert states["notifier"] == ("disconnected" if stack.is_postgres else "unknown")


def test_notifier_is_connected_while_a_listener_connection_is_open(stack: Stack) -> None:
    if not stack.is_postgres:
        pytest.skip("pg_stat_activity is Postgres only.")
    dsn = stack.database_url.replace("postgresql+psycopg://", "postgresql://")

    with psycopg.connect(dsn, application_name=NOTIFIER_LISTENER_APPLICATION_NAME):
        assert _states(stack)["notifier"] == "connected"

    assert _states(stack)["notifier"] == "disconnected"


@pytest.mark.parametrize(
    ("outcome", "state"),
    [
        ("answered", "healthy"),
        ("out_of_credits", "healthy"),
        ("client_error", "healthy"),
        ("network_error", "unhealthy"),
        ("server_error", "unhealthy"),
        ("auth_failure", "unhealthy"),
        # Recorded before outcomes were kept: never read as Healthy.
        (None, "unknown"),
    ],
)
def test_provider_follows_the_newest_upstream_call(
    stack: Stack, outcome: str | None, state: str
) -> None:
    # An older call of the opposite kind: only the newest one counts.
    stack.call("answered" if state != "healthy" else "server_error", 10)
    stack.call(outcome, 1)

    assert _states(stack)["provider"] == state


def test_provider_reads_upstream_calls_not_refresh_records(stack: Stack) -> None:
    stack.call("answered", 10)
    # A refresh that finished later, after a slow ingestion, does not decide.
    stack.refresh("failed", 1, "UPSTREAM_HTTP")

    assert _states(stack)["provider"] == "healthy"


def test_a_failing_paused_balance_check_turns_the_provider_unhealthy(stack: Stack) -> None:
    stack.call("out_of_credits", 10)
    stack.refresh("refused", 10, "OUT_OF_USAGE_CREDITS")
    assert _states(stack)["provider"] == "healthy"

    provider = stack.provider()
    with (
        patch.object(provider._client, "get", side_effect=httpx.ConnectError("refused")),
        pytest.raises(httpx.ConnectError),
    ):
        provider.check_quota()

    assert _states(stack)["provider"] == "unhealthy"


@pytest.mark.parametrize(
    ("status", "body", "state"),
    [
        (200, [], "healthy"),
        (401, {"error_code": "OUT_OF_USAGE_CREDITS"}, "healthy"),
        (401, {"message": "invalid api key"}, "unhealthy"),
        (500, {}, "unhealthy"),
    ],
)
def test_a_recorded_balance_check_outcome_round_trips_to_provider_state(
    stack: Stack, status: int, body: Any, state: str
) -> None:
    provider = stack.provider()
    response = httpx.Response(
        status, json=body, request=httpx.Request("GET", "https://api.the-odds-api.com/v4/sports")
    )
    with patch.object(provider._client, "get", return_value=response):
        try:
            provider.check_quota()
        except Exception:
            pass

    assert _states(stack)["provider"] == state


def test_empty_metrics(stack: Stack) -> None:
    body = stack.client.get("/api/v1/admin/metrics").json()

    assert body["last_successful_refresh"] is None
    assert body["credits"] is None
    assert {row["status"]: row["count"] for row in body["delivery_counts"]} == {
        "pending": 0,
        "delivered": 0,
        "failed": 0,
        "expired": 0,
        "gone": 0,
    }
    assert body["pending_deliveries"] == {"count": 0, "oldest_created_at": None}


def test_metrics_match_the_stored_refresh_quota_and_delivery_rows(stack: Stack) -> None:
    stack.refresh("succeeded", 30, sport="basketball_nba")
    stack.refresh("succeeded", 20, sport="icehockey_nhl")
    stack.refresh("failed", 5, "UPSTREAM_HTTP")
    stack.quota(remaining=200, used=300, minutes_ago=40)
    stack.quota(remaining=90, used=410, minutes_ago=5)
    stack.floor(100)
    stack.delivery("delivered", 1)
    stack.delivery("delivered", 2)
    stack.delivery("failed", 3)
    stack.delivery("gone", 23)
    stack.delivery("delivered", 25)  # outside the 24h window
    stack.delivery("pending", 30)  # pending counts are not windowed
    stack.delivery("pending", 0.5)

    metrics = stack.service.metrics()

    assert metrics.last_successful_refresh is not None
    assert metrics.last_successful_refresh.sport_key == "icehockey_nhl"
    assert metrics.last_successful_refresh.finished_at == NOW - timedelta(minutes=20)
    assert metrics.credits is not None
    assert (
        metrics.credits.remaining,
        metrics.credits.used,
        metrics.credits.floor,
        metrics.credits.out_of_credits,
        metrics.credits.below_floor,
    ) == (90, 410, 100, False, True)
    assert metrics.credits.observed_at == NOW - timedelta(minutes=5)
    assert metrics.deliveries_since == NOW - timedelta(hours=24)
    assert {c.status.value: c.count for c in metrics.delivery_counts} == {
        "pending": 1,
        "delivered": 2,
        "failed": 1,
        "expired": 0,
        "gone": 1,
    }
    assert metrics.pending_deliveries.count == 2
    assert metrics.pending_deliveries.oldest_created_at == NOW - timedelta(hours=30)


def test_metrics_never_return_a_push_address(stack: Stack) -> None:
    stack.delivery("pending", 1)

    response = stack.client.get("/api/v1/admin/metrics")

    assert response.status_code == 200
    assert "push.example" not in response.text


def test_nothing_left_counts_as_out_of_credits_as_the_credits_tab_shows(stack: Stack) -> None:
    # A local-count row at 0 is not a refusal, but the Credits tab reads it as out.
    stack.quota(remaining=0, used=500, minutes_ago=1)

    credits = stack.client.get("/api/v1/admin/metrics").json()["credits"]

    assert credits["out_of_credits"] is True
    assert credits["below_floor"] is True


def test_derived_floor_applies_when_none_is_configured(stack: Stack) -> None:
    stack.quota(remaining=40, used=460, minutes_ago=1)

    credits = stack.client.get("/api/v1/admin/metrics").json()["credits"]

    # 10% of the 500-credit plan.
    assert credits["floor"] == 50
    assert credits["below_floor"] is True
