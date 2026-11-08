import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, text

from backend.app.config import Settings
from backend.app.domain.public_events import (
    DESTINATION_TEST_V1,
    OPPORTUNITY_IDENTIFIED_V1,
    QUOTA_WARNING_V1,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.migrations import _build_alembic_config
from backend.app.infrastructure.persistence.schema import (
    deliveries_table,
    destinations_table,
    public_events_table,
)
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "contracts" / "events" / "examples"
PUSH_ADDRESS = "https://web.push.apple.com/QSecretSubscriptionToken"
P256DH = "p256dh-secret-key"
AUTH = "auth-secret-key"
T0 = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def _database_urls() -> list[Any]:
    urls: list[Any] = [pytest.param("sqlite", id="sqlite")]
    urls.append(
        pytest.param(
            os.environ.get("STAGE2_TEST_DATABASE_URL"),
            id="postgres",
            marks=pytest.mark.skipif(
                not os.environ.get("STAGE2_TEST_DATABASE_URL"),
                reason="Postgres integration environment is not configured.",
            ),
        )
    )
    return urls


class Log:
    """A migrated database and an app over it, with helpers to write the rows
    the Go notifier would."""

    def __init__(self, database_url: str) -> None:
        self.session_factory: DatabaseSessionFactory = prepare_test_database(
            database_url, seed_demo=False, drop_existing=not database_url.startswith("sqlite")
        )
        self.client = TestClient(create_app(Settings(database_url_override=database_url)))
        self._events = 0

    def destination(self, destination_id: str, label: str) -> str:
        with self.session_factory.create_session() as session:
            session.execute(
                insert(destinations_table).values(
                    id=destination_id,
                    channel="web_push",
                    label=label,
                    address=f"{PUSH_ADDRESS}-{destination_id}",
                    config={"p256dh": P256DH, "auth": AUTH},
                )
            )
            session.commit()
        return destination_id

    def event(self, event_type: str) -> str:
        self._events += 1
        event_id = f"evt-{self._events}"
        payload = json.loads((EXAMPLES_DIR / f"{event_type}.json").read_text())
        payload["id"] = event_id
        with self.session_factory.create_session() as session:
            session.execute(
                insert(public_events_table).values(id=event_id, type=event_type, payload=payload)
            )
            session.commit()
        return event_id

    def delivery(
        self,
        delivery_id: str,
        event_id: str,
        destination_id: str,
        status: str,
        minutes: int,
        last_error: str | None = None,
    ) -> None:
        created_at = T0 + timedelta(minutes=minutes)
        with self.session_factory.create_session() as session:
            session.execute(
                insert(deliveries_table).values(
                    id=delivery_id,
                    event_id=event_id,
                    destination_id=destination_id,
                    status=status,
                    attempts=1,
                    last_error=last_error,
                    created_at=created_at,
                    ended_at=None if status == "pending" else created_at + timedelta(seconds=5),
                )
            )
            session.commit()


@pytest.fixture(params=_database_urls())
def log(request: pytest.FixtureRequest, sqlite_database_url: str) -> Iterator[Log]:
    url = sqlite_database_url if request.param == "sqlite" else request.param
    built = Log(url)
    try:
        yield built
    finally:
        built.session_factory.engine.dispose()


def _seed(log: Log) -> None:
    phone = log.destination("dest-phone", "iPhone")
    mac = log.destination("dest-mac", "Mac")
    opportunity = log.event(OPPORTUNITY_IDENTIFIED_V1)
    test = log.event(DESTINATION_TEST_V1)
    warning = log.event(QUOTA_WARNING_V1)
    log.delivery("d1", opportunity, phone, "delivered", 1)
    log.delivery("d2", opportunity, mac, "failed", 2, "push service answered 400: bad")
    log.delivery("d3", test, phone, "expired", 3, "past its expiry before send")
    log.delivery("d4", warning, mac, "gone", 4, "push service answered 410: gone")
    log.delivery("d5", warning, phone, "pending", 5)


def test_an_empty_log_is_an_empty_first_page(log: Log) -> None:
    response = log.client.get("/api/v1/admin/deliveries")

    assert response.status_code == 200
    assert response.json() == {
        "deliveries": [],
        "page": 1,
        "page_size": 50,
        "total_items": 0,
        "total_pages": 0,
    }


def test_the_log_lists_every_delivery_newest_first_with_its_outcome(log: Log) -> None:
    _seed(log)

    body = log.client.get("/api/v1/admin/deliveries").json()

    assert [row["id"] for row in body["deliveries"]] == ["d5", "d4", "d3", "d2", "d1"]
    assert body["total_items"] == 5
    failed = body["deliveries"][3]
    assert failed == {
        "id": "d2",
        "event_id": "evt-1",
        "event_type": OPPORTUNITY_IDENTIFIED_V1,
        "subject": "Knicks @ Celtics · Knicks +125 @ DraftKings",
        "destination_id": "dest-mac",
        "destination_label": "Mac",
        "channel": "web_push",
        "status": "failed",
        "attempts": 1,
        "last_error": "push service answered 400: bad",
        "created_at": failed["created_at"],
        "ended_at": failed["ended_at"],
    }
    assert datetime.fromisoformat(failed["ended_at"]) == T0 + timedelta(minutes=2, seconds=5)
    assert body["deliveries"][0]["ended_at"] is None


def test_the_log_never_returns_a_push_address_key_or_raw_payload(log: Log) -> None:
    _seed(log)

    text = log.client.get("/api/v1/admin/deliveries").text

    for secret in (PUSH_ADDRESS, P256DH, AUTH):
        assert secret not in text
    # Fields only the raw opportunity payload carries.
    for raw in ("watch_intent_id", "matching", "nba-knicks-celtics", "FanDuel", "address"):
        assert raw not in text


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("status=failed", ["d2"]),
        ("status=pending", ["d5"]),
        (f"event_type={QUOTA_WARNING_V1}", ["d5", "d4"]),
        ("destination_id=dest-phone", ["d5", "d3", "d1"]),
        (f"destination_id=dest-mac&event_type={OPPORTUNITY_IDENTIFIED_V1}", ["d2"]),
        ("status=delivered&destination_id=dest-mac", []),
    ],
)
def test_filters_narrow_the_log_and_combine(log: Log, query: str, expected: list[str]) -> None:
    _seed(log)

    body = log.client.get(f"/api/v1/admin/deliveries?{query}").json()

    assert [row["id"] for row in body["deliveries"]] == expected
    assert body["total_items"] == len(expected)


def test_pages_split_the_log_without_repeating_a_row(log: Log) -> None:
    _seed(log)

    pages = [
        log.client.get(f"/api/v1/admin/deliveries?page={page}&page_size=2").json()
        for page in (1, 2, 3, 4)
    ]

    assert [[row["id"] for row in page["deliveries"]] for page in pages] == [
        ["d5", "d4"],
        ["d3", "d2"],
        ["d1"],
        [],
    ]
    assert {(page["total_items"], page["total_pages"]) for page in pages} == {(5, 3)}


@pytest.mark.parametrize(
    "query", ["status=sent", "page=0", "page_size=0", "page_size=201"]
)
def test_an_unknown_status_or_out_of_range_paging_is_rejected(log: Log, query: str) -> None:
    response = log.client.get(f"/api/v1/admin/deliveries?{query}")

    assert response.status_code == 422


def test_upgrading_stamps_delivered_rows_and_leaves_other_ended_rows_unknown(
    sqlite_database_url: str,
) -> None:
    """Before 0015 only a delivered row recorded when it ended."""
    config = _build_alembic_config(sqlite_database_url)
    # The revision just before 0015, whichever that is.
    command.upgrade(config, "20261108_0015-1")
    session_factory = DatabaseSessionFactory(sqlite_database_url)
    delivered_at = T0 + timedelta(minutes=1)
    with session_factory.create_session() as session:
        session.execute(
            text(
                "INSERT INTO destinations (id, channel, label, address, config) "
                "VALUES ('dest-1', 'web_push', 'iPhone', 'https://push.invalid/1', '{}')"
            )
        )
        for delivery_id, status, at in (
            ("d-delivered", "delivered", delivered_at),
            ("d-failed", "failed", None),
            ("d-pending", "pending", None),
        ):
            # One event per row: (event, destination) is unique.
            session.execute(
                text("INSERT INTO public_events (id, type, payload) VALUES (:id, :type, '{}')"),
                {"id": f"evt-{delivery_id}", "type": DESTINATION_TEST_V1},
            )
            session.execute(
                text(
                    "INSERT INTO deliveries (id, event_id, destination_id, status, delivered_at) "
                    "VALUES (:id, :event_id, 'dest-1', :status, :at)"
                ),
                {"id": delivery_id, "event_id": f"evt-{delivery_id}", "status": status, "at": at},
            )
        session.commit()

    command.upgrade(config, "head")

    with session_factory.create_session() as session:
        rows = session.execute(select(deliveries_table.c.id, deliveries_table.c.ended_at))
        ended: dict[str, datetime | None] = {row.id: row.ended_at for row in rows}
    session_factory.engine.dispose()
    assert ended["d-failed"] is None and ended["d-pending"] is None
    assert ended["d-delivered"] is not None
    assert ended["d-delivered"].replace(tzinfo=UTC) == delivered_at
