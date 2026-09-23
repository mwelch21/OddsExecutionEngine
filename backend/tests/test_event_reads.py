"""GET /events: a browsable, filterable page of events carrying honest quote age.

The list view is where someone decides whether a refresh is worth a request, so
every freshness assertion here checks that "we pulled recently" is never allowed
to stand in for "the books moved recently".
"""

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import insert
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.market_identity import build_line_key
from backend.app.infrastructure.persistence.schema import (
    event_participants_table,
    events_table,
    market_quotes_latest_table,
    markets_table,
)
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database

NOW = datetime.now(UTC)
PULLED_AT = NOW - timedelta(minutes=10)
MOVED_LONG_AGO = NOW - timedelta(days=3)
MOVED_RECENTLY = NOW - timedelta(minutes=20)

JsonDict = dict[str, Any]


def _insert_event(
    session: Session,
    *,
    external_id: str,
    sport: str,
    league: str,
    starts_at: datetime,
    participants: list[tuple[str, str]],
) -> str:
    event_row_id = str(uuid4())
    session.execute(
        insert(events_table).values(
            id=event_row_id,
            external_id=external_id,
            starts_at=starts_at,
            sport=sport,
            league=league,
        )
    )
    for order, (name, side) in enumerate(participants, start=1):
        session.execute(
            insert(event_participants_table).values(
                id=str(uuid4()),
                event_id=event_row_id,
                participant_name=name,
                role="team",
                side=side,
                sort_order=order,
            )
        )
    return event_row_id


def _insert_market(session: Session, *, event_row_id: str, selection: str) -> str:
    market_id = str(uuid4())
    session.execute(
        insert(markets_table).values(
            id=market_id,
            event_id=event_row_id,
            market_type="moneyline",
            selection=selection,
            line=None,
            line_key=build_line_key(None),
        )
    )
    return market_id


def _insert_quote(
    session: Session,
    *,
    market_id: str,
    sportsbook: str,
    price: int,
    ingested_at: datetime,
    quoted_at: datetime | None,
) -> None:
    session.execute(
        insert(market_quotes_latest_table).values(
            market_id=market_id,
            sportsbook=sportsbook,
            price=price,
            ingested_at=ingested_at,
            quoted_at=quoted_at,
        )
    )


def _seed_events(session_factory: DatabaseSessionFactory) -> None:
    """Three upcoming events across two leagues, plus one that has already started."""
    with session_factory.create_session() as session:
        # Three books quoting both sides, the way real ingestion stores them: a
        # book is not a row. Caesars reports no line-movement time on either
        # side, so it is one unknown-age book across two rows.
        nfl_quoted = _insert_event(
            session,
            external_id="nfl-chiefs-bills",
            sport="americanfootball",
            league="NFL",
            starts_at=NOW + timedelta(days=2),
            participants=[("Bills", "home"), ("Chiefs", "away")],
        )
        for selection in ("bills", "chiefs"):
            market_id = _insert_market(
                session, event_row_id=nfl_quoted, selection=selection
            )
            for sportsbook, quoted_at in (
                ("DraftKings", MOVED_LONG_AGO),
                ("BetMGM", MOVED_RECENTLY),
                ("Caesars", None),
            ):
                _insert_quote(
                    session,
                    market_id=market_id,
                    sportsbook=sportsbook,
                    price=-110,
                    ingested_at=PULLED_AT,
                    quoted_at=quoted_at,
                )

        # Never refreshed. Has no age at all, which is not the same as age zero.
        _insert_event(
            session,
            external_id="nfl-jets-dolphins",
            sport="americanfootball",
            league="NFL",
            starts_at=NOW + timedelta(days=1),
            participants=[("Dolphins", "home"), ("Jets", "away")],
        )

        mlb = _insert_event(
            session,
            external_id="mlb-yankees-redsox",
            sport="baseball",
            league="MLB",
            starts_at=NOW + timedelta(days=3),
            participants=[("Red Sox", "home"), ("Yankees", "away")],
        )
        _insert_quote(
            session,
            market_id=_insert_market(session, event_row_id=mlb, selection="yankees"),
            sportsbook="FanDuel",
            price=140,
            ingested_at=PULLED_AT,
            quoted_at=MOVED_RECENTLY,
        )

        started = _insert_event(
            session,
            external_id="nfl-already-kicked-off",
            sport="americanfootball",
            league="NFL",
            starts_at=NOW - timedelta(hours=1),
            participants=[("Eagles", "home"), ("Giants", "away")],
        )
        _insert_quote(
            session,
            market_id=_insert_market(session, event_row_id=started, selection="eagles"),
            sportsbook="DraftKings",
            price=100,
            ingested_at=PULLED_AT,
            quoted_at=MOVED_RECENTLY,
        )
        session.commit()


def _build_app(database_url: str, *, drop_existing: bool = False) -> FastAPI:
    session_factory = prepare_test_database(
        database_url, seed_demo=False, drop_existing=drop_existing
    )
    _seed_events(session_factory)
    return create_app(Settings(database_url_override=database_url))


def _ids(payload: JsonDict) -> list[str]:
    return [event["id"] for event in payload["events"]]


def _by_id(payload: JsonDict, event_id: str) -> JsonDict:
    return next(e for e in payload["events"] if e["id"] == event_id)


def test_lists_upcoming_events_with_participants_and_start_time(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        response = client.get("/events")

    assert response.status_code == 200
    payload = response.json()
    # Soonest first: the list is a schedule, so start time is the natural order.
    assert _ids(payload) == [
        "nfl-jets-dolphins",
        "nfl-chiefs-bills",
        "mlb-yankees-redsox",
    ]

    chiefs_bills = _by_id(payload, "nfl-chiefs-bills")
    assert chiefs_bills["league"] == "NFL"
    assert chiefs_bills["sport"] == "americanfootball"
    assert chiefs_bills["starts_at"] is not None
    assert [p["name"] for p in chiefs_bills["participants"]] == ["Bills", "Chiefs"]
    assert [p["side"] for p in chiefs_bills["participants"]] == ["home", "away"]


def test_events_that_have_started_are_excluded_by_default(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        default = client.get("/events").json()
        included = client.get("/events", params={"include_started": True}).json()

    assert "nfl-already-kicked-off" not in _ids(default)
    assert default["total_events"] == 3
    assert "nfl-already-kicked-off" in _ids(included)
    assert included["total_events"] == 4


def test_filters_by_league_and_by_sport_independently(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        by_league = client.get("/events", params={"league": "NFL"}).json()
        by_sport = client.get("/events", params={"sport": "baseball"}).json()
        both = client.get(
            "/events", params={"league": "MLB", "sport": "americanfootball"}
        ).json()

    assert _ids(by_league) == ["nfl-jets-dolphins", "nfl-chiefs-bills"]
    assert by_league["total_events"] == 2
    assert _ids(by_sport) == ["mlb-yankees-redsox"]
    # Both filters apply together rather than one overriding the other.
    assert _ids(both) == []
    assert both["total_events"] == 0
    assert both["total_pages"] == 0


def test_pagination_reports_enough_to_render_a_page_count(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        first = client.get("/events", params={"page": 1, "page_size": 2}).json()
        second = client.get("/events", params={"page": 2, "page_size": 2}).json()
        past_end = client.get("/events", params={"page": 9, "page_size": 2}).json()

    assert _ids(first) == ["nfl-jets-dolphins", "nfl-chiefs-bills"]
    assert first["page"] == 1
    assert first["page_size"] == 2
    assert first["total_events"] == 3
    assert first["total_pages"] == 2

    assert _ids(second) == ["mlb-yankees-redsox"]
    assert second["page"] == 2

    # A page beyond the end is empty, not an error: the set shifts under the reader.
    assert _ids(past_end) == []
    assert past_end["total_pages"] == 2


def test_pagination_rejects_nonsense_pages(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        assert client.get("/events", params={"page": 0}).status_code == 422
        assert client.get("/events", params={"page_size": 0}).status_code == 422
        assert client.get("/events", params={"page_size": 5000}).status_code == 422


def test_event_reports_when_we_pulled_and_the_oldest_line_among_its_books(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        payload = client.get("/events").json()

    quotes = _by_id(payload, "nfl-chiefs-bills")["quotes"]
    assert quotes["quote_count"] == 6
    _assert_same_instant(quotes["last_ingested_at"], PULLED_AT)
    # The oldest line among the books, not the most recent one and not the pull.
    _assert_same_instant(quotes["oldest_line_quoted_at"], MOVED_LONG_AGO)
    assert quotes["last_ingested_at"] != quotes["oldest_line_quoted_at"]


def test_books_with_no_line_movement_time_are_counted_not_folded_into_the_age(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        payload = client.get("/events").json()

    # Caesars quotes both sides, so it is two rows but one book. Counting rows
    # here would report two unknown books out of a book count of three.
    chiefs_bills = _by_id(payload, "nfl-chiefs-bills")["quotes"]
    assert chiefs_bills["quote_count"] == 6
    assert chiefs_bills["book_count"] == 3
    assert chiefs_bills["books_with_unknown_line_age"] == 1

    mlb = _by_id(payload, "mlb-yankees-redsox")["quotes"]
    assert mlb["book_count"] == 1
    assert mlb["books_with_unknown_line_age"] == 0


def test_event_with_no_quotes_reports_no_age_rather_than_zero_age(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        payload = client.get("/events").json()

    quotes = _by_id(payload, "nfl-jets-dolphins")["quotes"]
    assert quotes["quote_count"] == 0
    assert quotes["book_count"] == 0
    assert quotes["last_ingested_at"] is None
    assert quotes["oldest_line_quoted_at"] is None
    assert quotes["books_with_unknown_line_age"] == 0


def test_postgres_events_page_carries_filters_and_both_freshness_stamps() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    with TestClient(_build_app(database_url, drop_existing=True)) as client:
        page = client.get(
            "/events", params={"league": "NFL", "page": 1, "page_size": 1}
        ).json()
        full = client.get("/events").json()

    assert _ids(page) == ["nfl-jets-dolphins"]
    assert page["total_events"] == 2
    assert page["total_pages"] == 2
    assert "nfl-already-kicked-off" not in _ids(full)

    quotes = _by_id(full, "nfl-chiefs-bills")["quotes"]
    assert quotes["quote_count"] == 6
    assert quotes["book_count"] == 3
    assert quotes["books_with_unknown_line_age"] == 1
    _assert_same_instant(quotes["last_ingested_at"], PULLED_AT)
    _assert_same_instant(quotes["oldest_line_quoted_at"], MOVED_LONG_AGO)

    empty = _by_id(full, "nfl-jets-dolphins")["quotes"]
    assert empty["quote_count"] == 0
    assert empty["book_count"] == 0
    assert empty["last_ingested_at"] is None


def _assert_same_instant(reported: str, expected: datetime) -> None:
    """Times must come back as UTC instants, whatever the backend stored them as."""
    parsed = datetime.fromisoformat(reported)
    assert parsed.tzinfo is not None, reported
    assert abs(parsed - expected) < timedelta(seconds=1), reported
