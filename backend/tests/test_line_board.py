"""GET /events/{id}/quotes: one event's line board, grouped and ranked.

The board is what a reader compares books on, so every assertion here is about
the two things a client must not be left to work out for itself: which book is
best (including when two tie), and how old each price actually is.
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
from backend.app.domain.models import MarketType, Quote
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.recommendation_engine import RecommendationEngine
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

EVENT_ID = "nfl-chiefs-bills"
STARTED_EVENT_ID = "nfl-already-kicked-off"

JsonDict = dict[str, Any]


def _insert_event(
    session: Session,
    *,
    external_id: str,
    starts_at: datetime,
) -> str:
    event_row_id = str(uuid4())
    session.execute(
        insert(events_table).values(
            id=event_row_id,
            external_id=external_id,
            starts_at=starts_at,
            sport="americanfootball",
            league="NFL",
        )
    )
    for order, (name, side) in enumerate([("Bills", "home"), ("Chiefs", "away")], 1):
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


def _insert_market(
    session: Session,
    *,
    event_row_id: str,
    market_type: str,
    selection: str,
    line: float | None = None,
) -> str:
    market_id = str(uuid4())
    session.execute(
        insert(markets_table).values(
            id=market_id,
            event_id=event_row_id,
            market_type=market_type,
            selection=selection,
            line=line,
            line_key=build_line_key(line),
        )
    )
    return market_id


def _insert_quote(
    session: Session,
    *,
    market_id: str,
    sportsbook: str,
    price: int,
    quoted_at: datetime | None = MOVED_RECENTLY,
    ingested_at: datetime = PULLED_AT,
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


def _seed_board(session_factory: DatabaseSessionFactory) -> None:
    """One event with three markets: clear winner, a price tie, and an empty one."""
    with session_factory.create_session() as session:
        event_row_id = _insert_event(
            session, external_id=EVENT_ID, starts_at=NOW + timedelta(days=2)
        )

        moneyline = _insert_market(
            session,
            event_row_id=event_row_id,
            market_type="moneyline",
            selection="bills",
        )
        # DraftKings has the worst price and has not moved in days; Caesars
        # reports no line-movement time at all.
        _insert_quote(
            session,
            market_id=moneyline,
            sportsbook="DraftKings",
            price=-110,
            quoted_at=MOVED_LONG_AGO,
        )
        _insert_quote(session, market_id=moneyline, sportsbook="BetMGM", price=120)
        _insert_quote(
            session,
            market_id=moneyline,
            sportsbook="Caesars",
            price=-105,
            quoted_at=None,
        )

        # Two books tie at -105. Only the engine's tie-break decides which of
        # them a watch would fire on, so the board must not invent its own.
        spread = _insert_market(
            session,
            event_row_id=event_row_id,
            market_type="spread",
            selection="chiefs",
            line=-3.5,
        )
        _insert_quote(session, market_id=spread, sportsbook="Caesars", price=-105)
        _insert_quote(session, market_id=spread, sportsbook="BetMGM", price=-105)
        _insert_quote(session, market_id=spread, sportsbook="DraftKings", price=-115)

        # Known market, no book currently quoting it.
        _insert_market(
            session,
            event_row_id=event_row_id,
            market_type="total",
            selection="over",
            line=47.5,
        )

        started = _insert_event(
            session,
            external_id=STARTED_EVENT_ID,
            starts_at=NOW - timedelta(hours=1),
        )
        _insert_quote(
            session,
            market_id=_insert_market(
                session,
                event_row_id=started,
                market_type="moneyline",
                selection="eagles",
            ),
            sportsbook="DraftKings",
            price=100,
        )
        session.commit()


def _build_app(database_url: str, *, drop_existing: bool = False) -> FastAPI:
    session_factory = prepare_test_database(
        database_url, seed_demo=False, drop_existing=drop_existing
    )
    _seed_board(session_factory)
    return create_app(Settings(database_url_override=database_url))


def _board(client: TestClient, event_id: str = EVENT_ID) -> JsonDict:
    response = client.get(f"/events/{event_id}/quotes")
    assert response.status_code == 200, response.text
    payload: JsonDict = response.json()
    return payload


def _market(board: JsonDict, market_type: str, selection: str) -> JsonDict:
    return next(
        market
        for market in board["markets"]
        if market["market_type"] == market_type and market["selection"] == selection
    )


def test_board_groups_quotes_by_market_and_carries_the_event_header(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        board = _board(client)

    assert board["event"]["id"] == EVENT_ID
    assert [p["name"] for p in board["event"]["participants"]] == ["Bills", "Chiefs"]

    # Every market of the event, each holding its own books rather than one flat
    # list the client would have to regroup.
    assert [(m["market_type"], m["selection"], m["line"]) for m in board["markets"]] == [
        ("moneyline", "bills", None),
        ("spread", "chiefs", -3.5),
        ("total", "over", 47.5),
    ]
    moneyline = _market(board, "moneyline", "bills")
    assert {quote["sportsbook"] for quote in moneyline["quotes"]} == {
        "BetMGM",
        "Caesars",
        "DraftKings",
    }
    assert moneyline["book_count"] == 3


def test_quotes_are_ranked_best_first_and_the_best_book_is_named(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        board = _board(client)

    moneyline = _market(board, "moneyline", "bills")
    assert [q["sportsbook"] for q in moneyline["quotes"]] == [
        "BetMGM",
        "Caesars",
        "DraftKings",
    ]
    # The client is told the answer, not left to re-derive it from the list.
    assert moneyline["best_sportsbook"] == "BetMGM"
    assert moneyline["best_price"] == 120


def test_a_price_tie_breaks_the_same_way_the_engine_breaks_it(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        board = _board(client)

    spread = _market(board, "spread", "chiefs")
    engine = RecommendationEngine(PriceComparisonService())
    expected = engine.rank_quotes(
        [
            Quote(
                event_id=EVENT_ID,
                sportsbook=quote["sportsbook"],
                market_type=MarketType.SPREAD,
                selection="chiefs",
                price=quote["price"],
                line=-3.5,
            )
            for quote in spread["quotes"]
        ]
    )

    # Identical price, so only the engine's tie-break decides the order — and
    # the book a watch on this market would actually fire on.
    assert [q["sportsbook"] for q in spread["quotes"]] == [
        quote.sportsbook for quote in expected
    ]
    assert [q["sportsbook"] for q in spread["quotes"]] == [
        "BetMGM",
        "Caesars",
        "DraftKings",
    ]
    assert spread["best_sportsbook"] == "BetMGM"
    assert spread["best_price"] == -105


def test_each_quote_reports_the_books_clock_and_ours_separately(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        board = _board(client)

    quotes = {q["sportsbook"]: q for q in _market(board, "moneyline", "bills")["quotes"]}

    stale = quotes["DraftKings"]
    assert stale["line_age_known"] is True
    _assert_same_instant(stale["quoted_at"], MOVED_LONG_AGO)
    _assert_same_instant(stale["ingested_at"], PULLED_AT)
    # Pulled ten minutes ago, unmoved for three days. The board must show both.
    assert stale["quoted_at"] != stale["ingested_at"]

    current = quotes["BetMGM"]
    _assert_same_instant(current["quoted_at"], MOVED_RECENTLY)
    assert current["line_age_known"] is True

    # A book that exposes no line-movement time reads as unknown age, never as
    # freshly moved and never as the ingest time in disguise.
    unknown = quotes["Caesars"]
    assert unknown["quoted_at"] is None
    assert unknown["line_age_known"] is False
    _assert_same_instant(unknown["ingested_at"], PULLED_AT)


def test_a_market_no_book_is_quoting_is_present_and_empty(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        board = _board(client)

    total = _market(board, "total", "over")
    assert total["quotes"] == []
    assert total["book_count"] == 0
    # No quotes means no best book — not a best book at price zero.
    assert total["best_sportsbook"] is None
    assert total["best_price"] is None


def test_unknown_event_is_a_404(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        response = client.get("/events/no-such-event/quotes")

    assert response.status_code == 404


def test_board_is_not_paginated(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        board = _board(client)
        paged = client.get(
            f"/events/{EVENT_ID}/quotes", params={"page": 2, "page_size": 1}
        )

    assert not {"page", "page_size", "total_pages"} & board.keys()
    # Page params are meaningless here and must not be able to truncate a board.
    assert paged.status_code == 200
    assert len(paged.json()["markets"]) == len(board["markets"])


def test_a_started_event_still_renders_its_board(sqlite_database_url: str) -> None:
    with TestClient(_build_app(sqlite_database_url)) as client:
        board = _board(client, STARTED_EVENT_ID)

    # The browse list hides started events because they cannot be filled. Asking
    # for one by id is a different question, and it still has a line board.
    assert board["event"]["id"] == STARTED_EVENT_ID
    assert _market(board, "moneyline", "eagles")["best_sportsbook"] == "DraftKings"


def test_postgres_board_ranks_markets_and_breaks_a_tie() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    with TestClient(_build_app(database_url, drop_existing=True)) as client:
        board = _board(client)
        missing = client.get("/events/no-such-event/quotes")

    assert [(m["market_type"], m["selection"]) for m in board["markets"]] == [
        ("moneyline", "bills"),
        ("spread", "chiefs"),
        ("total", "over"),
    ]

    moneyline = _market(board, "moneyline", "bills")
    assert [q["sportsbook"] for q in moneyline["quotes"]] == [
        "BetMGM",
        "Caesars",
        "DraftKings",
    ]
    assert moneyline["best_sportsbook"] == "BetMGM"

    spread = _market(board, "spread", "chiefs")
    assert [q["sportsbook"] for q in spread["quotes"][:2]] == ["BetMGM", "Caesars"]
    assert spread["best_sportsbook"] == "BetMGM"

    unknown = next(q for q in moneyline["quotes"] if q["sportsbook"] == "Caesars")
    assert unknown["quoted_at"] is None
    assert unknown["line_age_known"] is False

    empty = _market(board, "total", "over")
    assert empty["quotes"] == []
    assert empty["best_sportsbook"] is None

    assert missing.status_code == 404


def _assert_same_instant(reported: str, expected: datetime) -> None:
    """Times must come back as UTC instants, whatever the backend stored them as."""
    parsed = datetime.fromisoformat(reported)
    assert parsed.tzinfo is not None, reported
    assert abs(parsed - expected) < timedelta(seconds=1), reported
