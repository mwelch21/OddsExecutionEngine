import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import insert, select, update

from backend.app.application.destination_service import DestinationService
from backend.app.config import Settings
from backend.app.domain.public_events import DESTINATION_TEST_V1
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    deliveries_table,
    destinations_table,
    public_events_table,
)
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database

ENDPOINT = "https://web.push.apple.com/QFakeSubscriptionToken"
PUBLIC_KEY = "BPublicKeyForTests"
CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "events"


def _build(
    database_url: str, *, drop_existing: bool = False
) -> tuple[FastAPI, DatabaseSessionFactory]:
    session_factory = prepare_test_database(
        database_url, seed_demo=False, drop_existing=drop_existing
    )
    app = create_app(
        Settings(database_url_override=database_url, vapid_public_key=PUBLIC_KEY)
    )
    return app, session_factory


def _subscription(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "endpoint": ENDPOINT,
        "keys": {"p256dh": "p256dh-1", "auth": "auth-secret-1"},
        "label": "iPhone",
    }
    payload.update(overrides)
    return payload


def _stored_rows(session_factory: DatabaseSessionFactory) -> list[dict[str, object]]:
    with session_factory.create_session() as session:
        return [
            dict(row)
            for row in session.execute(select(destinations_table)).mappings().all()
        ]


def test_vapid_public_key_is_served_when_configured(sqlite_database_url: str) -> None:
    app, _ = _build(sqlite_database_url)

    response = TestClient(app).get("/api/v1/push/vapid-public-key")

    assert response.status_code == 200
    assert response.json() == {"public_key": PUBLIC_KEY}


def test_vapid_public_key_is_unavailable_until_configured(sqlite_database_url: str) -> None:
    prepare_test_database(sqlite_database_url, seed_demo=False)
    # Explicitly empty: Settings would otherwise read a developer's real .env key.
    app = create_app(
        Settings(database_url_override=sqlite_database_url, vapid_public_key="")
    )

    response = TestClient(app).get("/api/v1/push/vapid-public-key")

    assert response.status_code == 503


def test_subscribing_creates_one_active_destination_without_exposing_secrets(
    sqlite_database_url: str,
) -> None:
    app, session_factory = _build(sqlite_database_url)
    client = TestClient(app)

    created = client.post("/api/v1/destinations/web-push", json=_subscription())
    listed = client.get("/api/v1/destinations")

    assert created.status_code == 201
    body = created.json()
    assert body["channel"] == "web_push"
    assert body["label"] == "iPhone"
    assert body["address"] == ENDPOINT
    assert body["active"] is True
    assert listed.json()["destinations"] == [body]
    for payload in (created.text, listed.text):
        assert "auth-secret-1" not in payload
        assert "p256dh-1" not in payload
        assert "config" not in payload

    rows = _stored_rows(session_factory)
    assert len(rows) == 1
    assert rows[0]["config"] == {"p256dh": "p256dh-1", "auth": "auth-secret-1"}


def test_subscribing_works_with_info_logging_enabled(
    sqlite_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The running API logs at INFO, and a log `extra` key that collides with a
    # LogRecord attribute raises only when the logger is live. In tests, Alembic's
    # in-process fileConfig disables loggers that already exist, which hid exactly
    # that crash, so the service logger is switched back on here.
    app, _ = _build(sqlite_database_url)
    monkeypatch.setattr(DestinationService._logger, "disabled", False)
    monkeypatch.setattr(DestinationService._logger, "level", logging.INFO)

    response = TestClient(app).post("/api/v1/destinations/web-push", json=_subscription())

    assert response.status_code == 201


def test_subscribing_again_updates_the_same_destination(sqlite_database_url: str) -> None:
    app, session_factory = _build(sqlite_database_url)
    client = TestClient(app)

    first = client.post("/api/v1/destinations/web-push", json=_subscription())
    second = client.post(
        "/api/v1/destinations/web-push",
        json=_subscription(keys={"p256dh": "p256dh-2", "auth": "auth-secret-2"}),
    )

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    rows = _stored_rows(session_factory)
    assert len(rows) == 1
    assert rows[0]["config"] == {"p256dh": "p256dh-2", "auth": "auth-secret-2"}


def test_resubscribing_revives_a_gone_destination_but_not_a_removed_one(
    sqlite_database_url: str,
) -> None:
    app, session_factory = _build(sqlite_database_url)
    client = TestClient(app)
    destination_id = client.post("/api/v1/destinations/web-push", json=_subscription()).json()["id"]

    def disable(reason: str) -> None:
        with session_factory.create_session() as session:
            session.execute(
                update(destinations_table)
                .where(destinations_table.c.id == destination_id)
                .values(disabled_at=datetime.now(UTC), disabled_reason=reason)
            )
            session.commit()

    disable("gone")
    revived = client.post("/api/v1/destinations/web-push", json=_subscription()).json()
    assert revived["active"] is True
    assert revived["disabled_reason"] is None

    disable("user_removed")
    kept = client.post("/api/v1/destinations/web-push", json=_subscription()).json()
    assert kept["active"] is False
    assert kept["disabled_reason"] == "user_removed"


@pytest.mark.parametrize(
    "overrides",
    [
        {"endpoint": "http://insecure.example/push"},
        {"keys": {"p256dh": "", "auth": "x"}},
        {"keys": {"p256dh": "x"}},
    ],
)
def test_malformed_subscriptions_are_rejected(
    sqlite_database_url: str, overrides: dict[str, object]
) -> None:
    app, session_factory = _build(sqlite_database_url)

    response = TestClient(app).post(
        "/api/v1/destinations/web-push", json=_subscription(**overrides)
    )

    assert response.status_code == 422
    assert _stored_rows(session_factory) == []


def test_postgres_subscription_is_idempotent_on_its_endpoint() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    app, session_factory = _build(database_url, drop_existing=True)
    try:
        client = TestClient(app)
        first = client.post("/api/v1/destinations/web-push", json=_subscription())
        second = client.post("/api/v1/destinations/web-push", json=_subscription(label="Renamed"))

        assert (first.status_code, second.status_code) == (201, 200)
        assert second.json()["id"] == first.json()["id"]
        # A re-subscription refreshes keys, never the operator's chosen label.
        assert second.json()["label"] == "iPhone"
        assert len(_stored_rows(session_factory)) == 1
    finally:
        session_factory.engine.dispose()


def test_send_test_queues_one_targeted_public_event(sqlite_database_url: str) -> None:
    app, session_factory = _build(sqlite_database_url)
    client = TestClient(app)
    destination_id = client.post("/api/v1/destinations/web-push", json=_subscription()).json()["id"]

    response = client.post(f"/api/v1/destinations/{destination_id}/test")

    assert response.status_code == 202
    with session_factory.create_session() as session:
        rows = session.execute(select(public_events_table)).mappings().all()
    assert len(rows) == 1
    payload = rows[0]["payload"]
    assert rows[0]["id"] == response.json()["public_event_id"]
    assert payload["type"] == DESTINATION_TEST_V1
    assert payload["subject"] == destination_id
    schema = json.loads((CONTRACTS_DIR / f"{DESTINATION_TEST_V1}.json").read_text())
    Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    ).validate(payload)


def test_send_test_is_rate_limited_per_destination(sqlite_database_url: str) -> None:
    app, _ = _build(sqlite_database_url)
    client = TestClient(app)
    first_id = client.post("/api/v1/destinations/web-push", json=_subscription()).json()["id"]
    second_id = client.post(
        "/api/v1/destinations/web-push",
        json=_subscription(endpoint="https://fcm.googleapis.com/other-device"),
    ).json()["id"]

    assert client.post(f"/api/v1/destinations/{first_id}/test").status_code == 202
    limited = client.post(f"/api/v1/destinations/{first_id}/test")
    other_device = client.post(f"/api/v1/destinations/{second_id}/test")

    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    assert other_device.status_code == 202


def test_send_test_rejects_unknown_and_disabled_destinations(
    sqlite_database_url: str,
) -> None:
    app, session_factory = _build(sqlite_database_url)
    client = TestClient(app)
    destination_id = client.post("/api/v1/destinations/web-push", json=_subscription()).json()["id"]
    with session_factory.create_session() as session:
        session.execute(
            update(destinations_table)
            .where(destinations_table.c.id == destination_id)
            .values(disabled_at=datetime.now(UTC), disabled_reason="gone")
        )
        session.commit()

    assert client.post("/api/v1/destinations/missing/test").status_code == 404
    assert client.post(f"/api/v1/destinations/{destination_id}/test").status_code == 409


def _register(client: TestClient, **overrides: object) -> str:
    response = client.post("/api/v1/destinations/web-push", json=_subscription(**overrides))
    return str(response.json()["id"])


def _mark_gone(session_factory: DatabaseSessionFactory, destination_id: str) -> None:
    with session_factory.create_session() as session:
        session.execute(
            update(destinations_table)
            .where(destinations_table.c.id == destination_id)
            .values(disabled_at=datetime.now(UTC), disabled_reason="gone")
        )
        session.commit()


def test_patch_renames_a_destination(sqlite_database_url: str) -> None:
    app, _ = _build(sqlite_database_url)
    client = TestClient(app)
    destination_id = _register(client)

    response = client.patch(f"/api/v1/destinations/{destination_id}", json={"label": "Work phone"})

    assert response.status_code == 200
    assert response.json()["label"] == "Work phone"
    assert client.get("/api/v1/destinations").json()["destinations"][0]["label"] == "Work phone"
    assert "auth-secret-1" not in response.text


@pytest.mark.parametrize("body", [{}, {"label": ""}, {"active": False}, {"label": "x" * 129}])
def test_patch_rejects_an_empty_or_invalid_change(
    sqlite_database_url: str, body: dict[str, object]
) -> None:
    app, _ = _build(sqlite_database_url)
    client = TestClient(app)
    destination_id = _register(client)

    assert client.patch(f"/api/v1/destinations/{destination_id}", json=body).status_code == 422


def test_delete_soft_disables_and_patch_re_enables(sqlite_database_url: str) -> None:
    app, session_factory = _build(sqlite_database_url)
    client = TestClient(app)
    destination_id = _register(client)

    removed = client.delete(f"/api/v1/destinations/{destination_id}")

    assert removed.status_code == 200
    assert removed.json()["active"] is False
    assert removed.json()["disabled_reason"] == "user_removed"
    rows = _stored_rows(session_factory)
    assert len(rows) == 1
    assert rows[0]["config"] == {"p256dh": "p256dh-1", "auth": "auth-secret-1"}
    assert client.post(f"/api/v1/destinations/{destination_id}/test").status_code == 409

    again = client.delete(f"/api/v1/destinations/{destination_id}")
    assert again.status_code == 200
    assert again.json()["disabled_at"] == removed.json()["disabled_at"]

    restored = client.patch(f"/api/v1/destinations/{destination_id}", json={"active": True})
    assert restored.status_code == 200
    assert restored.json()["active"] is True
    assert restored.json()["disabled_reason"] is None
    assert restored.json()["disabled_at"] is None


def test_gone_destination_cannot_be_re_enabled_or_relabelled_into_service(
    sqlite_database_url: str,
) -> None:
    app, session_factory = _build(sqlite_database_url)
    client = TestClient(app)
    destination_id = _register(client)
    _mark_gone(session_factory, destination_id)

    re_enable = client.patch(
        f"/api/v1/destinations/{destination_id}", json={"active": True, "label": "New"}
    )
    removed = client.delete(f"/api/v1/destinations/{destination_id}")

    assert re_enable.status_code == 409
    # The rejected PATCH changed nothing, and removing a gone one keeps it `gone`:
    # only a fresh subscription can bring it back.
    assert removed.status_code == 200
    assert removed.json()["label"] == "iPhone"
    assert removed.json()["disabled_reason"] == "gone"
    assert client.patch(
        f"/api/v1/destinations/{destination_id}", json={"label": "Old iPad"}
    ).json()["label"] == "Old iPad"


def test_patch_and_delete_reject_unknown_destinations(sqlite_database_url: str) -> None:
    app, _ = _build(sqlite_database_url)
    client = TestClient(app)

    assert client.patch("/api/v1/destinations/missing", json={"label": "x"}).status_code == 404
    assert client.delete("/api/v1/destinations/missing").status_code == 404


def test_postgres_remove_and_re_enable_keep_the_row_and_its_deliveries() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    app, session_factory = _build(database_url, drop_existing=True)
    try:
        client = TestClient(app)
        destination_id = _register(client)
        event_id = client.post(f"/api/v1/destinations/{destination_id}/test").json()[
            "public_event_id"
        ]
        with session_factory.create_session() as session:
            session.execute(
                insert(deliveries_table).values(
                    id="delivery-1",
                    event_id=event_id,
                    destination_id=destination_id,
                    status="delivered",
                )
            )
            session.commit()

        removed = client.delete(f"/api/v1/destinations/{destination_id}")
        renamed = client.patch(
            f"/api/v1/destinations/{destination_id}", json={"label": "Spare"}
        )
        test_while_removed = client.post(f"/api/v1/destinations/{destination_id}/test")
        restored = client.patch(f"/api/v1/destinations/{destination_id}", json={"active": True})

        assert removed.json()["disabled_reason"] == "user_removed"
        # Renaming a removed destination leaves it removed.
        assert renamed.json()["active"] is False
        assert test_while_removed.status_code == 409
        assert restored.json()["active"] is True
        assert restored.json()["label"] == "Spare"
        with session_factory.create_session() as session:
            deliveries = session.execute(select(deliveries_table)).mappings().all()
        assert [d["destination_id"] for d in deliveries] == [destination_id]
        assert len(_stored_rows(session_factory)) == 1
    finally:
        session_factory.engine.dispose()
