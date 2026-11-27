"""The allowed-books filter (#136): which books are shown, ranked and evaluated.

Unit tests pin the engines to the value object they are handed. Integration
tests run on migrated Postgres through the API: the setting itself, each surface
it applies to, and the two things it must never do (narrow ingestion, or touch
an opportunity that already triggered).
"""

import os
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from backend.app.config import Settings
from backend.app.domain.book_filter import ALL_BOOKS, BookFilter
from backend.app.domain.models import (
    MarketType,
    OrderIntent,
    Quote,
    WatchIntent,
    WatchStatus,
    WatchWindow,
)
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine
from backend.app.infrastructure.persistence.book_filter_uow import (
    SqlAlchemyBookFilterUnitOfWork,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.migrations import _build_alembic_config
from backend.app.infrastructure.persistence.schema import (
    market_quotes_latest_table,
    opportunities_table,
)
from backend.app.infrastructure.quote_provider import FIXTURE_EVENT_ID
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database

JsonDict = dict[str, Any]

EVENT = "event-1"


def _quote(sportsbook: str, price: int, selection: str = "knicks") -> Quote:
    return Quote(
        event_id=EVENT,
        sportsbook=sportsbook,
        market_type=MarketType.MONEYLINE,
        selection=selection,
        price=price,
    )


QUOTES = [_quote("BetMGM", 120), _quote("DraftKings", 125), _quote("FanDuel", 110)]


def _intent(target_price: int) -> OrderIntent:
    return OrderIntent(
        event_id=EVENT,
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=target_price,
    )


def _recommend(target_price: int, book_filter: BookFilter) -> Any:
    price_comparison = PriceComparisonService()
    matched = QuoteMatchingEngine().match_quotes(_intent(target_price), QUOTES, book_filter)
    return RecommendationEngine(price_comparison).generate_recommendation(
        _intent(target_price), matched
    )


def _watch_engine() -> WatchEvaluationEngine:
    price_comparison = PriceComparisonService()
    return WatchEvaluationEngine(price_comparison, RecommendationEngine(price_comparison))


def _watch(target_price: int) -> WatchIntent:
    return WatchIntent(
        id="wi-1",
        event_id=EVENT,
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=target_price,
        window=WatchWindow.FULL_GAME,
        status=WatchStatus.ACTIVE,
    )


LOOKUP: dict[tuple[str, str, str, float | None], str] = {
    (EVENT, "moneyline", "knicks", None): "market-1"
}


# --- Value object ----------------------------------------------------------------


def test_filter_is_sorted_and_unique_and_empty_admits_every_book() -> None:
    book_filter = BookFilter(sportsbooks=("FanDuel", "BetMGM", "FanDuel"))

    assert book_filter.sportsbooks == ("BetMGM", "FanDuel")
    assert book_filter.admits("BetMGM")
    assert not book_filter.admits("DraftKings")
    assert ALL_BOOKS.allows_all
    assert ALL_BOOKS.admits("AnyBook")
    assert [q.sportsbook for q in book_filter.apply(QUOTES)] == ["BetMGM", "FanDuel"]


# --- Recommendation --------------------------------------------------------------


def test_recommendation_ranks_and_fills_from_allowed_books_only() -> None:
    recommendation = _recommend(115, BookFilter(sportsbooks=("BetMGM", "FanDuel")))

    assert recommendation.fillable is True
    # DraftKings has the best price but is not allowed.
    assert recommendation.best_quote.sportsbook == "BetMGM"
    assert [q.sportsbook for q in recommendation.ranked_quotes] == ["BetMGM", "FanDuel"]
    assert recommendation.matched_quote_count == 2


def test_nearest_miss_comes_from_an_allowed_book() -> None:
    recommendation = _recommend(130, BookFilter(sportsbooks=("FanDuel",)))

    assert recommendation.fillable is False
    assert recommendation.nearest_miss.sportsbook == "FanDuel"


def test_an_empty_filter_keeps_every_book() -> None:
    recommendation = _recommend(115, ALL_BOOKS)

    assert recommendation.best_quote.sportsbook == "DraftKings"
    assert recommendation.matched_quote_count == 3


# --- Watch evaluation ------------------------------------------------------------


def test_watch_does_not_trigger_on_a_price_from_a_book_outside_the_filter() -> None:
    opportunities = _watch_engine().evaluate(
        [_watch(121)], QUOTES, LOOKUP, BookFilter(sportsbooks=("BetMGM", "FanDuel"))
    )

    assert opportunities == []


def test_watch_lists_only_allowed_books_in_its_opportunity() -> None:
    opportunities = _watch_engine().evaluate(
        [_watch(115)], QUOTES, LOOKUP, BookFilter(sportsbooks=("BetMGM", "FanDuel"))
    )

    assert len(opportunities) == 1
    assert opportunities[0].best_sportsbook == "BetMGM"
    assert [q.sportsbook for q in opportunities[0].matching_quotes] == ["BetMGM"]


def test_watch_with_an_empty_filter_uses_every_book() -> None:
    opportunities = _watch_engine().evaluate([_watch(121)], QUOTES, LOOKUP)

    assert opportunities[0].best_sportsbook == "DraftKings"


# --- Postgres ----------------------------------------------------------------------


def _postgres_url() -> str:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")
    return database_url


def _app(database_url: str) -> FastAPI:
    # Demo quotes on the fixture event, moneyline knicks: BetMGM 120,
    # DraftKings 125, FanDuel 125; moneyline celtics: Caesars -145.
    prepare_test_database(database_url, seed_demo=True, drop_existing=True)
    return create_app(Settings(database_url_override=database_url, quote_provider="in_memory"))


def _put(client: TestClient, books: list[str]) -> JsonDict:
    response = client.put("/api/v1/admin/book-filter", json={"sportsbooks": books})
    assert response.status_code == 200, response.text
    body: JsonDict = response.json()
    return body


def _market(board: JsonDict, market_type: str, selection: str) -> JsonDict:
    market: JsonDict = next(
        m
        for m in board["markets"]
        if (m["market_type"], m["selection"]) == (market_type, selection)
    )
    return market


def _watch_payload(target_price: int) -> JsonDict:
    return {
        "event_id": FIXTURE_EVENT_ID,
        "market_type": "moneyline",
        "selection": "knicks",
        "target_price": target_price,
    }


def test_postgres_setting_defaults_to_all_books_and_lists_stored_books() -> None:
    with TestClient(_app(_postgres_url())) as client:
        initial = client.get("/api/v1/admin/book-filter").json()
        saved = _put(client, ["FanDuel", "BetMGM", "FanDuel"])
        reread = client.get("/api/v1/admin/book-filter").json()
        cleared = client.put("/api/v1/admin/book-filter", json={}).json()

    assert initial == {
        "sportsbooks": [],
        "available_sportsbooks": ["BetMGM", "Caesars", "DraftKings", "FanDuel"],
    }
    assert saved["sportsbooks"] == ["BetMGM", "FanDuel"]
    assert reread["sportsbooks"] == ["BetMGM", "FanDuel"]
    assert cleared["sportsbooks"] == []


def test_postgres_unknown_book_is_rejected_and_nothing_is_saved() -> None:
    with TestClient(_app(_postgres_url())) as client:
        _put(client, ["BetMGM"])
        response = client.put(
            "/api/v1/admin/book-filter", json={"sportsbooks": ["BetMGM", "NoSuchBook"]}
        )
        after = client.get("/api/v1/admin/book-filter").json()

    assert response.status_code == 422
    assert "NoSuchBook" in response.json()["detail"]
    assert after["sportsbooks"] == ["BetMGM"]


def test_postgres_a_held_book_stays_valid_after_its_quotes_are_gone() -> None:
    database_url = _postgres_url()
    with TestClient(_app(database_url)) as client:
        _put(client, ["BetMGM", "Caesars"])
        session_factory = DatabaseSessionFactory(database_url)
        try:
            with session_factory.engine.begin() as connection:
                connection.execute(
                    market_quotes_latest_table.delete().where(
                        market_quotes_latest_table.c.sportsbook == "Caesars"
                    )
                )
        finally:
            session_factory.engine.dispose()
        resaved = _put(client, ["BetMGM", "Caesars"])

    assert resaved["sportsbooks"] == ["BetMGM", "Caesars"]
    assert "Caesars" not in resaved["available_sportsbooks"]


def test_postgres_line_board_and_events_list_show_allowed_books_only() -> None:
    with TestClient(_app(_postgres_url())) as client:
        before = client.get("/api/v1/events").json()["events"][0]["quotes"]
        _put(client, ["BetMGM"])
        board = client.get(f"/api/v1/events/{FIXTURE_EVENT_ID}/quotes").json()
        after = client.get("/api/v1/events").json()["events"][0]["quotes"]

    knicks = _market(board, "moneyline", "knicks")
    assert [q["sportsbook"] for q in knicks["quotes"]] == ["BetMGM"]
    assert knicks["best_sportsbook"] == "BetMGM"
    # Only Caesars quotes this market: it stays on the board, empty.
    celtics = _market(board, "moneyline", "celtics")
    assert celtics["quotes"] == []
    assert celtics["best_sportsbook"] is None
    assert board["event"]["quotes"]["book_count"] == 1

    assert (before["book_count"], before["quote_count"]) == (4, 10)
    assert (after["book_count"], after["quote_count"]) == (1, 3)


def test_postgres_recommendation_uses_allowed_books_only() -> None:
    with TestClient(_app(_postgres_url())) as client:
        _put(client, ["BetMGM"])
        response = client.post(
            "/api/v1/execution/recommendation", json=_watch_payload(121)
        )

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["fillable"] is False
    assert body["nearest_miss"]["sportsbook"] == "BetMGM"
    assert [q["sportsbook"] for q in body["ranked_quotes"]] == ["BetMGM"]


def test_postgres_watch_triggers_only_on_an_allowed_book() -> None:
    with TestClient(_app(_postgres_url())) as client:
        _put(client, ["BetMGM"])
        blocked = client.post("/api/v1/watch-intents", json=_watch_payload(121))
        _put(client, [])
        open_ = client.post("/api/v1/watch-intents", json=_watch_payload(121))

    assert blocked.status_code == 201, blocked.text
    assert blocked.json()["status"] == "active"
    assert open_.json()["status"] == "triggered"


def test_postgres_refresh_evaluates_watches_with_the_filter_and_stores_every_book() -> None:
    database_url = _postgres_url()
    with TestClient(_app(database_url)) as client:
        _put(client, ["BetMGM"])
        watch = client.post("/api/v1/watch-intents", json=_watch_payload(121)).json()
        refresh = client.post(
            "/api/v1/ingestion/quotes/refresh", json={"event_id": FIXTURE_EVENT_ID}
        )
        after_refresh = client.get(f"/api/v1/watch-intents/{watch['id']}").json()
        # The next evaluation uses the new list; nothing re-evaluated on save.
        _put(client, ["DraftKings"])
        after_change = client.get(f"/api/v1/watch-intents/{watch['id']}").json()
        client.post("/api/v1/ingestion/quotes/refresh", json={"event_id": FIXTURE_EVENT_ID})
        after_next_refresh = client.get(f"/api/v1/watch-intents/{watch['id']}").json()

    assert refresh.status_code == 200, refresh.text
    # Ingestion is unchanged: all four books are stored.
    assert refresh.json()["ingested_quote_count"] == 10
    session_factory = DatabaseSessionFactory(database_url)
    try:
        with session_factory.create_session() as session:
            books = session.execute(
                select(func.count(market_quotes_latest_table.c.sportsbook.distinct()))
            ).scalar_one()
    finally:
        session_factory.engine.dispose()
    assert books == 4

    assert after_refresh["status"] == "active"
    assert after_change["status"] == "active"
    assert after_next_refresh["status"] == "triggered"


def test_postgres_changing_the_filter_leaves_triggered_opportunities_alone() -> None:
    database_url = _postgres_url()
    with TestClient(_app(database_url)) as client:
        triggered = client.post("/api/v1/watch-intents", json=_watch_payload(121)).json()
        before = client.get("/api/v1/opportunities").json()
        _put(client, ["BetMGM"])
        after = client.get("/api/v1/opportunities").json()
        watch = client.get(f"/api/v1/watch-intents/{triggered['id']}").json()

    assert triggered["status"] == "triggered"
    assert before == after
    assert watch["status"] == "triggered"
    session_factory = DatabaseSessionFactory(database_url)
    try:
        with session_factory.create_session() as session:
            count = session.execute(select(func.count()).select_from(opportunities_table))
            assert count.scalar_one() == 1
    finally:
        session_factory.engine.dispose()


def test_postgres_migration_creates_the_table_and_downgrades_cleanly() -> None:
    database_url = _postgres_url()
    prepare_test_database(database_url, seed_demo=False, drop_existing=True).engine.dispose()
    config = _build_alembic_config(database_url)
    session_factory = DatabaseSessionFactory(database_url)
    try:
        command.downgrade(config, "20261127_0021")
        with session_factory.engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT to_regclass('public.book_filter_settings')")
                ).scalar_one()
                is None
            )
        command.upgrade(config, "head")

        with SqlAlchemyBookFilterUnitOfWork(session_factory) as uow:
            assert uow.get_book_filter() == ALL_BOOKS
            uow.save_book_filter(BookFilter(sportsbooks=("FanDuel", "BetMGM")))
        with SqlAlchemyBookFilterUnitOfWork(session_factory) as uow:
            assert uow.get_book_filter().sportsbooks == ("BetMGM", "FanDuel")
    finally:
        session_factory.engine.dispose()
