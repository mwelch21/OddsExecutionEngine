"""The refresh log (#103): every refresh leaves one record, and the operator reads them.

Each test runs on SQLite and on migrated Postgres; the Postgres leg skips when no
integration database is configured.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from backend.app.config import Settings
from backend.app.domain.quota import OutOfUsageCreditsError
from backend.app.domain.refresh_records import (
    RefreshOutcomeStatus,
    RefreshRecord,
    RefreshScope,
    RefreshTrigger,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.refresh_records import SqlAlchemyRefreshRecorder
from backend.app.infrastructure.quote_provider import FIXTURE_EVENT_ID, InMemoryQuoteProvider
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database
from backend.tests.test_auto_refresh import FIXTURE_SPORT_KEY, Harness

T0 = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


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
def client(database_url: str, session_factory: DatabaseSessionFactory) -> TestClient:
    return TestClient(create_app(Settings(database_url_override=database_url)))


def _refreshes(client: TestClient, **params: str | int) -> dict[str, Any]:
    response = client.get("/api/v1/admin/refreshes", params=params)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _rows(client: TestClient, **params: str | int) -> list[dict[str, Any]]:
    rows = _refreshes(client, **params)["refreshes"]
    assert isinstance(rows, list)
    return rows


def _record(
    sport: str, trigger: RefreshTrigger, outcome: RefreshOutcomeStatus, minute: int
) -> RefreshRecord:
    return RefreshRecord(
        scope=RefreshScope.SPORT,
        sport_key=sport,
        trigger=trigger,
        started_at=T0 + timedelta(minutes=minute),
        finished_at=T0 + timedelta(minutes=minute, seconds=2),
        outcome=outcome,
        events_refreshed=1 if outcome is RefreshOutcomeStatus.SUCCEEDED else 0,
    )


def test_the_log_is_empty_before_the_first_refresh(client: TestClient) -> None:
    assert _refreshes(client) == {
        "refreshes": [],
        "page": 1,
        "page_size": 50,
        "total_items": 0,
        "total_pages": 0,
    }


def test_a_manual_sport_refresh_leaves_one_sport_wide_manual_record(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ingestion/quotes/refresh-sport", json={"sport": FIXTURE_SPORT_KEY}
    )
    assert response.status_code == 200

    [row] = _rows(client)
    assert {k: row[k] for k in ("scope", "sport", "event_id", "trigger", "outcome")} == {
        "scope": "sport",
        "sport": FIXTURE_SPORT_KEY,
        "event_id": None,
        "trigger": "manual",
        "outcome": "succeeded",
    }
    assert row["events_refreshed"] == 1
    assert (row["error_code"], row["error"]) == (None, None)
    assert str(row["started_at"]) <= str(row["finished_at"])


def test_a_manual_event_refresh_leaves_one_event_record(client: TestClient) -> None:
    response = client.post("/api/v1/ingestion/quotes/refresh", json={"event_id": FIXTURE_EVENT_ID})
    assert response.status_code == 200

    [row] = _rows(client)
    assert (row["scope"], row["sport"], row["event_id"], row["trigger"], row["outcome"]) == (
        "event",
        FIXTURE_SPORT_KEY,
        FIXTURE_EVENT_ID,
        "manual",
        "succeeded",
    )
    assert row["events_refreshed"] == 1


def test_an_auto_refresh_leaves_one_auto_record_and_is_the_last_outcome(
    database_url: str, client: TestClient
) -> None:
    # The schema is already migrated; the harness only truncates and reseeds.
    harness = Harness(database_url)
    try:
        harness.switch(True)
        harness.add_watch()
        harness.service.run_cycle()
        # A later manual refresh is in the log but is not Auto-Refresh's last outcome.
        harness.ingestion.refresh_sport(FIXTURE_SPORT_KEY)

        rows = _rows(client)
        assert [(r["trigger"], r["scope"]) for r in rows] == [
            ("manual", "sport"),
            ("auto", "sport"),
        ]
        last = client.get("/api/v1/admin/auto-refresh").json()["last_outcome"]
        assert last == {
            "sport": FIXTURE_SPORT_KEY,
            "status": "succeeded",
            "at": rows[1]["finished_at"],
            "events_refreshed": 1,
            "error": None,
        }
    finally:
        harness.close()


def test_a_failed_refresh_is_recorded_and_still_raises(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(self: object, sport: str) -> object:
        raise RuntimeError("upstream 500")

    monkeypatch.setattr(InMemoryQuoteProvider, "list_quotes_for_sport", fail)

    with pytest.raises(RuntimeError, match="upstream 500"):
        client.post("/api/v1/ingestion/quotes/refresh-sport", json={"sport": FIXTURE_SPORT_KEY})

    [row] = _rows(client)
    assert (row["outcome"], row["error_code"], row["error"], row["events_refreshed"]) == (
        "failed",
        "RuntimeError",
        "upstream 500",
        0,
    )


def test_a_refused_refresh_is_recorded_and_the_503_is_unchanged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: object, event_id: str, sport: str) -> object:
        raise OutOfUsageCreditsError()

    monkeypatch.setattr(InMemoryQuoteProvider, "list_quotes", refuse)

    response = client.post("/api/v1/ingestion/quotes/refresh", json={"event_id": FIXTURE_EVENT_ID})

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "OUT_OF_USAGE_CREDITS", "message": str(OutOfUsageCreditsError())}
    }
    [row] = _rows(client)
    assert (row["scope"], row["outcome"], row["error_code"]) == (
        "event",
        "refused",
        "OUT_OF_USAGE_CREDITS",
    )


def test_a_rejected_request_is_not_a_refresh(client: TestClient) -> None:
    unknown_sport = client.post("/api/v1/ingestion/quotes/refresh-sport", json={"sport": "curling"})
    unknown_event = client.post("/api/v1/ingestion/quotes/refresh", json={"event_id": "nope"})

    assert (unknown_sport.status_code, unknown_event.status_code) == (422, 404)
    assert _rows(client) == []


def test_failing_to_write_the_record_never_fails_the_refresh(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: object, record: RefreshRecord) -> None:
        raise RuntimeError("refresh_records is unwritable")

    monkeypatch.setattr(SqlAlchemyRefreshRecorder, "record", broken)

    response = client.post(
        "/api/v1/ingestion/quotes/refresh-sport", json={"sport": FIXTURE_SPORT_KEY}
    )

    assert response.status_code == 200
    assert response.json()["sport"] == FIXTURE_SPORT_KEY
    assert _rows(client) == []


def test_the_log_is_newest_first_filtered_and_paged(
    session_factory: DatabaseSessionFactory, client: TestClient
) -> None:
    recorder = SqlAlchemyRefreshRecorder(session_factory)
    succeeded, failed = RefreshOutcomeStatus.SUCCEEDED, RefreshOutcomeStatus.FAILED
    auto, manual = RefreshTrigger.AUTO, RefreshTrigger.MANUAL
    for minute, (sport, trigger, outcome) in enumerate(
        [
            ("basketball_nba", auto, succeeded),
            ("icehockey_nhl", manual, failed),
            ("basketball_nba", manual, succeeded),
            ("basketball_nba", auto, failed),
            ("icehockey_nhl", auto, succeeded),
        ]
    ):
        recorder.record(_record(sport, trigger, outcome, minute))

    newest_first = [r["started_at"] for r in _rows(client)]
    assert newest_first == sorted(newest_first, reverse=True)
    assert len(newest_first) == 5

    page_two = _refreshes(client, page=2, page_size=2)
    assert (page_two["total_items"], page_two["total_pages"]) == (5, 3)
    assert [r["started_at"] for r in page_two["refreshes"]] == newest_first[2:4]
    assert _refreshes(client, page=4, page_size=2)["refreshes"] == []

    nba_auto = _rows(client, sport="basketball_nba", trigger="auto")
    assert [r["outcome"] for r in nba_auto] == ["failed", "succeeded"]
    assert _refreshes(client, outcome="failed")["total_items"] == 2


def test_paging_and_filters_are_validated(client: TestClient) -> None:
    for params in (
        {"page": 0},
        {"page_size": 0},
        {"page_size": 201},
        {"trigger": "cron"},
        {"outcome": "partial"},
    ):
        assert client.get("/api/v1/admin/refreshes", params=params).status_code == 422
    assert _refreshes(client, page_size=200)["page_size"] == 200


def test_the_last_outcome_columns_are_gone_after_migration(
    session_factory: DatabaseSessionFactory,
) -> None:
    inspector = inspect(session_factory.engine)
    columns = {column["name"] for column in inspector.get_columns("auto_refresh_settings")}
    indexes = {index["name"] for index in inspector.get_indexes("refresh_records")}

    assert not {c for c in columns if c.startswith("last_outcome")}
    assert "ix_refresh_records_started_at" in indexes
