import logging
import os
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from backend.app.application.destination_service import DestinationService
from backend.app.config import Settings
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import destinations_table
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database

ENDPOINT = "https://web.push.apple.com/QFakeSubscriptionToken"
PUBLIC_KEY = "BPublicKeyForTests"


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

    response = TestClient(app).get("/push/vapid-public-key")

    assert response.status_code == 200
    assert response.json() == {"public_key": PUBLIC_KEY}


def test_vapid_public_key_is_unavailable_until_configured(sqlite_database_url: str) -> None:
    prepare_test_database(sqlite_database_url, seed_demo=False)
    # Explicitly empty: Settings would otherwise read a developer's real .env key.
    app = create_app(
        Settings(database_url_override=sqlite_database_url, vapid_public_key="")
    )

    response = TestClient(app).get("/push/vapid-public-key")

    assert response.status_code == 503


def test_subscribing_creates_one_active_destination_without_exposing_secrets(
    sqlite_database_url: str,
) -> None:
    app, session_factory = _build(sqlite_database_url)
    client = TestClient(app)

    created = client.post("/destinations/web-push", json=_subscription())
    listed = client.get("/destinations")

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

    response = TestClient(app).post("/destinations/web-push", json=_subscription())

    assert response.status_code == 201


def test_subscribing_again_updates_the_same_destination(sqlite_database_url: str) -> None:
    app, session_factory = _build(sqlite_database_url)
    client = TestClient(app)

    first = client.post("/destinations/web-push", json=_subscription())
    second = client.post(
        "/destinations/web-push",
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
    destination_id = client.post("/destinations/web-push", json=_subscription()).json()["id"]

    def disable(reason: str) -> None:
        with session_factory.create_session() as session:
            session.execute(
                update(destinations_table)
                .where(destinations_table.c.id == destination_id)
                .values(disabled_at=datetime.now(UTC), disabled_reason=reason)
            )
            session.commit()

    disable("gone")
    revived = client.post("/destinations/web-push", json=_subscription()).json()
    assert revived["active"] is True
    assert revived["disabled_reason"] is None

    disable("user_removed")
    kept = client.post("/destinations/web-push", json=_subscription()).json()
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

    response = TestClient(app).post("/destinations/web-push", json=_subscription(**overrides))

    assert response.status_code == 422
    assert _stored_rows(session_factory) == []


def test_postgres_subscription_is_idempotent_on_its_endpoint() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    app, session_factory = _build(database_url, drop_existing=True)
    try:
        client = TestClient(app)
        first = client.post("/destinations/web-push", json=_subscription())
        second = client.post("/destinations/web-push", json=_subscription(label="Renamed"))

        assert (first.status_code, second.status_code) == (201, 200)
        assert second.json()["id"] == first.json()["id"]
        # A re-subscription refreshes keys, never the operator's chosen label.
        assert second.json()["label"] == "iPhone"
        assert len(_stored_rows(session_factory)) == 1
    finally:
        session_factory.engine.dispose()
