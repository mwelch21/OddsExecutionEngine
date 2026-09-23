import os

import pytest
from sqlalchemy import select

from backend.app.domain.models import MarketType, MatchingQuote, Opportunity, WatchStatus
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import opportunities_table
from backend.app.infrastructure.persistence.seed import truncate_application_tables
from backend.app.infrastructure.persistence.watch_intent_uow import (
    SqlAlchemyWatchIntentUnitOfWork,
)
from backend.app.infrastructure.quote_provider import FIXTURE_EVENT_ID
from backend.tests.db_helpers import prepare_test_database


def test_create_opportunities_allows_only_one_row_per_watch(
    sqlite_database_url: str,
) -> None:
    session_factory, watch_intent_id, market_id = _create_watch_context(
        sqlite_database_url
    )
    first = _make_opportunity(
        opportunity_id="opp-1",
        watch_intent_id=watch_intent_id,
        market_id=market_id,
        best_sportsbook="DraftKings",
        best_price=125,
    )
    # A different book entirely: under the old per-book identity this was a legal
    # second row. The watch is terminal now, so it is not.
    second = _make_opportunity(
        opportunity_id="opp-2",
        watch_intent_id=watch_intent_id,
        market_id=market_id,
        best_sportsbook="FanDuel",
        best_price=130,
    )

    with SqlAlchemyWatchIntentUnitOfWork(session_factory) as uow:
        inserted = uow.create_opportunities([first])
    assert [opp.id for opp in inserted] == ["opp-1"]

    with SqlAlchemyWatchIntentUnitOfWork(session_factory) as uow:
        inserted = uow.create_opportunities([second])
    assert inserted == []

    with session_factory.create_session() as session:
        rows = session.execute(select(opportunities_table)).mappings().all()

    assert len(rows) == 1
    assert rows[0]["id"] == "opp-1"


def test_opportunity_round_trips_every_matching_book(
    sqlite_database_url: str,
) -> None:
    session_factory, watch_intent_id, market_id = _create_watch_context(
        sqlite_database_url
    )
    opportunity = _make_opportunity(
        opportunity_id="opp-1",
        watch_intent_id=watch_intent_id,
        market_id=market_id,
        best_sportsbook="DraftKings",
        best_price=125,
        also_matching=[("FanDuel", 125), ("Caesars", 122)],
    )

    with SqlAlchemyWatchIntentUnitOfWork(session_factory) as uow:
        uow.create_opportunities([opportunity])

    with SqlAlchemyWatchIntentUnitOfWork(session_factory) as uow:
        stored = uow.get_opportunity("opp-1")

    assert stored is not None
    assert stored.best_sportsbook == "DraftKings"
    assert stored.best_price == 125
    assert [(q.sportsbook, q.price) for q in stored.matching_quotes] == [
        ("DraftKings", 125),
        ("FanDuel", 125),
        ("Caesars", 122),
    ]


def test_trigger_watch_intents_retires_the_watch(sqlite_database_url: str) -> None:
    session_factory, watch_intent_id, _ = _create_watch_context(sqlite_database_url)

    with SqlAlchemyWatchIntentUnitOfWork(session_factory) as uow:
        triggered = uow.trigger_watch_intents([watch_intent_id])

    with SqlAlchemyWatchIntentUnitOfWork(session_factory) as uow:
        still_active = uow.list_active_watch_intents(FIXTURE_EVENT_ID)
        stored = uow.get_watch_intent(watch_intent_id)

    assert [intent.status for intent in triggered] == [WatchStatus.TRIGGERED]
    assert stored is not None
    assert stored.status is WatchStatus.TRIGGERED
    assert [intent.id for intent in still_active] == []


def test_validity_lookup_keys_on_the_best_book_only(
    sqlite_database_url: str,
) -> None:
    session_factory, watch_intent_id, market_id = _create_watch_context(
        sqlite_database_url
    )
    # "NoSuchBook" has no latest quote row; if the lookup keyed on any listed book
    # this would still find a time and report the opportunity valid.
    opportunity = _make_opportunity(
        opportunity_id="opp-1",
        watch_intent_id=watch_intent_id,
        market_id=market_id,
        best_sportsbook="NoSuchBook",
        best_price=125,
        also_matching=[("DraftKings", 125)],
    )

    with SqlAlchemyWatchIntentUnitOfWork(session_factory) as uow:
        uow.create_opportunities([opportunity])

    with SqlAlchemyWatchIntentUnitOfWork(session_factory) as uow:
        stored = uow.get_opportunity("opp-1")
        assert stored is not None
        items = uow.get_latest_quote_times([stored])

    assert items[0][1] is None


def test_postgres_create_opportunities_allows_only_one_row_per_watch() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    session_factory = prepare_test_database(
        database_url,
        seed_demo=True,
        drop_existing=True,
    )
    try:
        _, watch_intent_id, market_id = _create_watch_context(
            database_url,
            session_factory=session_factory,
        )
        first = _make_opportunity(
            opportunity_id="opp-1",
            watch_intent_id=watch_intent_id,
            market_id=market_id,
            best_sportsbook="DraftKings",
            best_price=125,
            also_matching=[("FanDuel", 125)],
        )
        duplicate = _make_opportunity(
            opportunity_id="opp-2",
            watch_intent_id=watch_intent_id,
            market_id=market_id,
            best_sportsbook="FanDuel",
            best_price=130,
        )

        with SqlAlchemyWatchIntentUnitOfWork(session_factory) as uow:
            inserted = uow.create_opportunities([first])
        assert [opp.id for opp in inserted] == ["opp-1"]

        with SqlAlchemyWatchIntentUnitOfWork(session_factory) as uow:
            inserted = uow.create_opportunities([duplicate])
        assert inserted == []

        with session_factory.create_session() as session:
            rows = session.execute(select(opportunities_table)).mappings().all()

        assert len(rows) == 1
        assert rows[0]["id"] == "opp-1"
    finally:
        truncate_application_tables(session_factory)


def _create_watch_context(
    database_url: str,
    *,
    session_factory: DatabaseSessionFactory | None = None,
) -> tuple[DatabaseSessionFactory, str, str]:
    target_session_factory = session_factory or prepare_test_database(
        database_url,
        seed_demo=True,
    )
    with SqlAlchemyWatchIntentUnitOfWork(target_session_factory) as uow:
        intent = uow.create_watch_intent(
            event_id=FIXTURE_EVENT_ID,
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            target_price=121,
            line=None,
        )
        market_id_lookup = uow.get_market_id_lookup(FIXTURE_EVENT_ID)

    market_id = market_id_lookup[(FIXTURE_EVENT_ID, "moneyline", "knicks", None)]
    return target_session_factory, intent.id, market_id


def _make_opportunity(
    *,
    opportunity_id: str,
    watch_intent_id: str,
    market_id: str,
    best_sportsbook: str,
    best_price: int,
    also_matching: list[tuple[str, int]] | None = None,
) -> Opportunity:
    return Opportunity(
        id=opportunity_id,
        watch_intent_id=watch_intent_id,
        event_id=FIXTURE_EVENT_ID,
        market_id=market_id,
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=121,
        best_sportsbook=best_sportsbook,
        best_price=best_price,
        matching_quotes=[MatchingQuote(sportsbook=best_sportsbook, price=best_price)]
        + [
            MatchingQuote(sportsbook=book, price=price)
            for book, price in (also_matching or [])
        ],
    )
