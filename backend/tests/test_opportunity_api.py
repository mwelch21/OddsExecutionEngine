import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.config import Settings
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    opportunity_signals_table,
    watch_intents_table,
    workflow_events_table,
)
from backend.app.infrastructure.persistence.seed import truncate_application_tables
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database

EVENT_ID = "nba-knicks-celtics-2026-04-11"


def _build_app(database_url: str) -> FastAPI:
    prepare_test_database(database_url, seed_demo=False)
    return create_app(Settings(database_url_override=database_url))


def _watch_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_id": EVENT_ID,
        "market_type": "moneyline",
        "selection": "knicks",
        "target_price": 120,
    }
    payload.update(overrides)
    return payload


def _refresh(client: TestClient) -> None:
    response = client.post("/ingestion/quotes/refresh", json={"event_id": EVENT_ID})
    assert response.status_code == 200


def test_quote_refresh_triggers_watch_and_creates_opportunity(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        created = client.post("/watch-intents", json=_watch_payload()).json()
        _refresh(client)

        watch_after = client.get(f"/watch-intents/{created['id']}").json()
        opportunities = client.get("/opportunities").json()["opportunities"]

    assert watch_after["status"] == "triggered"
    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity["watch_intent_id"] == created["id"]
    assert opportunity["event_id"] == EVENT_ID
    assert opportunity["market_type"] == "moneyline"
    assert opportunity["selection"] == "knicks"
    assert opportunity["target_price"] == 120
    assert opportunity["matched_price"] == 125
    assert opportunity["sportsbook"] == "DraftKings"


def test_unfilled_watch_stays_active_after_refresh(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        created = client.post("/watch-intents", json=_watch_payload(target_price=300)).json()
        _refresh(client)

        watch_after = client.get(f"/watch-intents/{created['id']}").json()
        opportunities = client.get("/opportunities").json()["opportunities"]

    assert watch_after["status"] == "active"
    assert opportunities == []


def test_expired_watch_is_marked_expired_during_evaluation(sqlite_database_url: str) -> None:
    expires_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

    with TestClient(_build_app(sqlite_database_url)) as client:
        created = client.post(
            "/watch-intents",
            json=_watch_payload(expires_at=expires_at),
        ).json()
        _refresh(client)

        watch_after = client.get(f"/watch-intents/{created['id']}").json()
        opportunities = client.get("/opportunities").json()["opportunities"]

    assert watch_after["status"] == "expired"
    assert opportunities == []

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    with session_factory.create_session() as session:
        event_types = [
            row["event_type"]
            for row in session.execute(select(workflow_events_table)).mappings()
        ]

    assert "WatchIntentExpired" in event_types
    assert "TargetPriceBecameFillable" not in event_types


def test_cancelled_watch_is_not_evaluated(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        created = client.post("/watch-intents", json=_watch_payload()).json()
        client.delete(f"/watch-intents/{created['id']}")
        _refresh(client)

        watch_after = client.get(f"/watch-intents/{created['id']}").json()
        opportunities = client.get("/opportunities").json()["opportunities"]

    assert watch_after["status"] == "cancelled"
    assert opportunities == []


def test_triggered_watch_is_not_re_evaluated_on_later_refresh(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        client.post("/watch-intents", json=_watch_payload())
        _refresh(client)
        _refresh(client)

        opportunities = client.get("/opportunities").json()["opportunities"]

    assert len(opportunities) == 1


def test_opportunities_are_filterable_by_event_and_readable_by_id(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        client.post("/watch-intents", json=_watch_payload())
        _refresh(client)

        created = client.get("/opportunities").json()["opportunities"][0]
        by_event = client.get("/opportunities", params={"event_id": EVENT_ID})
        other_event = client.get("/opportunities", params={"event_id": "other-event"})
        found = client.get(f"/opportunities/{created['id']}")
        missing = client.get("/opportunities/does-not-exist")

    assert [item["id"] for item in by_event.json()["opportunities"]] == [created["id"]]
    assert other_event.json()["opportunities"] == []
    assert found.status_code == 200
    assert found.json()["id"] == created["id"]
    assert missing.status_code == 404


def test_watch_evaluation_persists_opportunity_and_events_in_one_transaction(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        client.post("/watch-intents", json=_watch_payload())
        _refresh(client)

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    with session_factory.create_session() as session:
        stored_opportunity = session.execute(select(opportunity_signals_table)).mappings().one()
        stored_watch = session.execute(select(watch_intents_table)).mappings().one()
        event_types = [
            row["event_type"]
            for row in session.execute(select(workflow_events_table)).mappings()
        ]

    assert stored_opportunity["watch_intent_id"] == stored_watch["id"]
    assert stored_opportunity["event_external_id"] == EVENT_ID
    assert stored_watch["status"] == "triggered"
    assert event_types.count("TargetPriceBecameFillable") == 1


def test_postgres_is_required_truth_path_for_watch_evaluation() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    session_factory = prepare_test_database(database_url, seed_demo=False, drop_existing=True)
    app = create_app(Settings(database_url_override=database_url))

    try:
        with TestClient(app) as client:
            created = client.post("/watch-intents", json=_watch_payload()).json()
            expired = client.post(
                "/watch-intents",
                json=_watch_payload(
                    target_price=300,
                    expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                ),
            ).json()
            _refresh(client)

            triggered_watch = client.get(f"/watch-intents/{created['id']}").json()
            expired_watch = client.get(f"/watch-intents/{expired['id']}").json()
            opportunities = client.get(
                "/opportunities",
                params={"event_id": EVENT_ID},
            ).json()["opportunities"]

        assert triggered_watch["status"] == "triggered"
        assert expired_watch["status"] == "expired"
        assert len(opportunities) == 1
        assert opportunities[0]["watch_intent_id"] == created["id"]
        assert opportunities[0]["matched_price"] == 125
        assert opportunities[0]["sportsbook"] == "DraftKings"

        with session_factory.create_session() as session:
            stored_opportunities = (
                session.execute(select(opportunity_signals_table)).mappings().all()
            )
            event_types = [
                row["event_type"]
                for row in session.execute(select(workflow_events_table)).mappings()
            ]

        assert len(stored_opportunities) == 1
        assert event_types.count("TargetPriceBecameFillable") == 1
        assert event_types.count("WatchIntentExpired") == 1
    finally:
        truncate_application_tables(session_factory)
