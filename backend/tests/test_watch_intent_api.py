from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.config import Settings
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    watch_intents_table,
    workflow_events_table,
)
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database

EVENT_ID = "nba-knicks-celtics-2026-04-11"


def _build_app(database_url: str) -> FastAPI:
    prepare_test_database(database_url, seed_demo=True)
    return create_app(Settings(database_url_override=database_url))


def _create_watch_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_id": EVENT_ID,
        "market_type": "moneyline",
        "selection": "knicks",
        "target_price": 130,
    }
    payload.update(overrides)
    return payload


def test_create_watch_intent_returns_active_watch(sqlite_database_url: str) -> None:
    expires_at = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    with TestClient(_build_app(sqlite_database_url)) as client:
        response = client.post(
            "/watch-intents",
            json=_create_watch_payload(expires_at=expires_at),
        )

    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["event_id"] == EVENT_ID
    assert body["market_type"] == "moneyline"
    assert body["selection"] == "knicks"
    assert body["target_price"] == 130
    assert body["line"] is None
    assert body["status"] == "active"
    assert body["expires_at"] is not None


def test_create_watch_intent_persists_row_and_workflow_event(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        response = client.post("/watch-intents", json=_create_watch_payload())

    assert response.status_code == 201

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    with session_factory.create_session() as session:
        stored_watch = session.execute(select(watch_intents_table)).mappings().one()
        stored_events = session.execute(select(workflow_events_table)).mappings().all()

    assert stored_watch["event_external_id"] == EVENT_ID
    assert stored_watch["status"] == "active"
    assert stored_watch["target_price"] == 130
    assert [event["event_type"] for event in stored_events] == ["WatchIntentSubmitted"]
    assert stored_events[0]["aggregate_id"] == stored_watch["id"]


def test_create_watch_intent_validates_market_fields(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        moneyline_with_line = client.post(
            "/watch-intents",
            json=_create_watch_payload(line=1.5),
        )
        total_without_line = client.post(
            "/watch-intents",
            json=_create_watch_payload(market_type="total", selection="over"),
        )
        total_bad_selection = client.post(
            "/watch-intents",
            json=_create_watch_payload(market_type="total", selection="knicks", line=221.5),
        )

    assert moneyline_with_line.status_code == 422
    assert total_without_line.status_code == 422
    assert total_bad_selection.status_code == 422


def test_list_watch_intents_filters_by_event_and_status(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        first = client.post("/watch-intents", json=_create_watch_payload()).json()
        second = client.post(
            "/watch-intents",
            json=_create_watch_payload(event_id="other-event"),
        ).json()
        client.delete(f"/watch-intents/{second['id']}")

        all_watches = client.get("/watch-intents")
        by_event = client.get("/watch-intents", params={"event_id": EVENT_ID})
        by_status = client.get("/watch-intents", params={"status": "cancelled"})

    assert all_watches.status_code == 200
    assert len(all_watches.json()["watch_intents"]) == 2
    assert [watch["id"] for watch in by_event.json()["watch_intents"]] == [first["id"]]
    assert [watch["id"] for watch in by_status.json()["watch_intents"]] == [second["id"]]


def test_get_watch_intent_returns_watch_or_404(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        created = client.post("/watch-intents", json=_create_watch_payload()).json()
        found = client.get(f"/watch-intents/{created['id']}")
        missing = client.get("/watch-intents/does-not-exist")

    assert found.status_code == 200
    assert found.json()["id"] == created["id"]
    assert missing.status_code == 404


def test_delete_watch_intent_soft_cancels_and_is_idempotent(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        created = client.post("/watch-intents", json=_create_watch_payload()).json()
        first_cancel = client.delete(f"/watch-intents/{created['id']}")
        second_cancel = client.delete(f"/watch-intents/{created['id']}")
        missing_cancel = client.delete("/watch-intents/does-not-exist")

    assert first_cancel.status_code == 200
    assert first_cancel.json()["status"] == "cancelled"
    assert second_cancel.status_code == 200
    assert second_cancel.json()["status"] == "cancelled"
    assert missing_cancel.status_code == 404

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    with session_factory.create_session() as session:
        stored_watch = session.execute(select(watch_intents_table)).mappings().one()
        event_types = [
            row["event_type"] for row in session.execute(select(workflow_events_table)).mappings()
        ]

    assert stored_watch["status"] == "cancelled"
    assert event_types == ["WatchIntentSubmitted", "WatchIntentCancelled"]
