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


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_id": EVENT_ID,
        "market_type": "moneyline",
        "selection": "knicks",
        "target_price": 400,
    }
    payload.update(overrides)
    return payload


def _past() -> str:
    return (datetime.now(UTC) - timedelta(minutes=5)).isoformat()


def _future() -> str:
    return (datetime.now(UTC) + timedelta(hours=2)).isoformat()


def test_watch_intent_round_trips_its_ttl(sqlite_database_url: str) -> None:
    expires_at = _future()

    with TestClient(_build_app(sqlite_database_url)) as client:
        created = client.post("/watch-intents", json=_payload(expires_at=expires_at))
        fetched = client.get(f"/watch-intents/{created.json()['id']}")

    assert created.status_code == 201
    assert created.json()["expires_at"] is not None
    assert created.json()["status"] == "active"
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created.json()["id"]


def test_watch_intent_without_ttl_still_works(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        created = client.post("/watch-intents", json=_payload())

    assert created.status_code == 201
    assert created.json()["expires_at"] is None


def test_get_watch_intent_returns_404_when_unknown(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        response = client.get("/watch-intents/does-not-exist")

    assert response.status_code == 404


def test_get_opportunity_returns_404_when_unknown(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        response = client.get("/opportunities/does-not-exist")

    assert response.status_code == 404


def test_watch_past_its_ttl_reads_as_expired_before_any_evaluation(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        created = client.post("/watch-intents", json=_payload(expires_at=_past())).json()
        live = client.post("/watch-intents", json=_payload(expires_at=_future())).json()

        fetched = client.get(f"/watch-intents/{created['id']}").json()
        active = client.get("/watch-intents", params={"status": "active"}).json()
        expired = client.get("/watch-intents", params={"status": "expired"}).json()
        default_listing = client.get("/watch-intents").json()

    assert fetched["status"] == "expired"
    assert [w["id"] for w in expired["watch_intents"]] == [created["id"]]
    assert [w["id"] for w in active["watch_intents"]] == [live["id"]]
    assert [w["id"] for w in default_listing["watch_intents"]] == [live["id"]]

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    with session_factory.create_session() as session:
        stored = (
            session.execute(
                select(watch_intents_table).where(watch_intents_table.c.id == created["id"])
            )
            .mappings()
            .one()
        )

    assert stored["status"] == "active"


def test_expired_watch_is_retired_and_never_fills_on_refresh(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        # target_price 100 is reachable: the fixture book has knicks moneyline at +125.
        expired = client.post(
            "/watch-intents",
            json=_payload(target_price=100, expires_at=_past()),
        ).json()

        refresh = client.post("/ingestion/quotes/refresh", json={"event_id": EVENT_ID})

        after = client.get(f"/watch-intents/{expired['id']}").json()
        opportunities = client.get(
            "/opportunities", params={"event_id": EVENT_ID}
        ).json()["opportunities"]

    assert refresh.status_code == 200
    assert after["status"] == "expired"
    assert [o for o in opportunities if o["watch_intent_id"] == expired["id"]] == []

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    with session_factory.create_session() as session:
        stored = (
            session.execute(
                select(watch_intents_table).where(watch_intents_table.c.id == expired["id"])
            )
            .mappings()
            .one()
        )
        event_types = [
            row["event_type"]
            for row in session.execute(select(workflow_events_table)).mappings()
        ]

    assert stored["status"] == "expired"
    assert "WatchIntentExpired" in event_types


def test_live_watch_fills_once_and_is_terminal(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        live = client.post(
            "/watch-intents",
            json=_payload(target_price=100, expires_at=_future()),
        ).json()

        client.post("/ingestion/quotes/refresh", json={"event_id": EVENT_ID})

        after = client.get(f"/watch-intents/{live['id']}").json()
        opportunities = client.get(
            "/opportunities", params={"event_id": EVENT_ID}
        ).json()["opportunities"]

    matching = [o for o in opportunities if o["watch_intent_id"] == live["id"]]

    assert after["status"] == "triggered"
    assert len(matching) == 1
    assert matching[0]["best_price"] >= 100
    assert all(q["price"] >= 100 for q in matching[0]["matching_quotes"])


def test_triggered_watch_is_not_re_evaluated_and_never_re_arms(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        live = client.post("/watch-intents", json=_payload(target_price=100)).json()

        # Two further refreshes: a sixth book qualifying later must emit nothing,
        # and an opportunity going stale must not send the watch back to active.
        client.post("/ingestion/quotes/refresh", json={"event_id": EVENT_ID})
        client.post("/ingestion/quotes/refresh", json={"event_id": EVENT_ID})

        after = client.get(f"/watch-intents/{live['id']}").json()
        opportunities = client.get(
            "/opportunities", params={"event_id": EVENT_ID}
        ).json()["opportunities"]

    mine = [o for o in opportunities if o["watch_intent_id"] == live["id"]]

    assert after["status"] == "triggered"
    assert len(mine) == 1
    # The refreshes moved the quote on, so the snapshot is stale — and the watch
    # still does not re-arm. Staleness is reported, never acted on.
    assert mine[0]["is_valid"] is False
    assert mine[0]["invalid_reason"] == "quote_superseded"

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    with session_factory.create_session() as session:
        event_types = [
            row["event_type"]
            for row in session.execute(select(workflow_events_table)).mappings()
        ]

    assert event_types.count("OpportunityIdentified") == 1
    assert event_types.count("WatchIntentTriggered") == 1


def test_create_returns_the_opportunity_it_filled_immediately(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        created = client.post("/watch-intents", json=_payload(target_price=100))

    body = created.json()

    assert created.status_code == 201
    assert body["status"] == "triggered"
    assert body["opportunity"] is not None
    assert body["opportunity"]["best_sportsbook"] == "DraftKings"
    # Every book at or above +100, ranked best-first with the +125 tie broken
    # alphabetically — one opportunity, not three.
    assert [
        (q["sportsbook"], q["price"]) for q in body["opportunity"]["matching_quotes"]
    ] == [("DraftKings", 125), ("FanDuel", 125), ("BetMGM", 120)]


def test_create_omits_the_opportunity_when_nothing_filled(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        created = client.post("/watch-intents", json=_payload(target_price=400))

    assert created.json()["status"] == "active"
    assert created.json()["opportunity"] is None


def test_a_triggered_watch_cannot_be_cancelled(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        triggered = client.post(
            "/watch-intents", json=_payload(target_price=100)
        ).json()

        cancelled = client.delete(f"/watch-intents/{triggered['id']}")
        after = client.get(f"/watch-intents/{triggered['id']}").json()

    # Cancelling a fired watch would erase the record that it fired.
    assert cancelled.status_code == 409
    assert after["status"] == "triggered"


def test_single_opportunity_read_matches_the_listing(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        client.post("/watch-intents", json=_payload(target_price=100))
        listed = client.get("/opportunities", params={"event_id": EVENT_ID}).json()[
            "opportunities"
        ]
        fetched = client.get(f"/opportunities/{listed[0]['id']}")

    assert listed != []
    assert fetched.status_code == 200
    assert fetched.json()["id"] == listed[0]["id"]
    assert fetched.json()["best_sportsbook"] == listed[0]["best_sportsbook"]
    assert fetched.json()["matching_quotes"] == listed[0]["matching_quotes"]
    assert fetched.json()["is_valid"] == listed[0]["is_valid"]
