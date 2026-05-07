import os

import pytest
from sqlalchemy import select

from backend.app.domain.models import MarketType, Opportunity
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import opportunities_table
from backend.app.infrastructure.persistence.seed import truncate_application_tables
from backend.app.infrastructure.persistence.watch_intent_uow import (
    SqlAlchemyWatchIntentUnitOfWork,
)
from backend.app.infrastructure.quote_provider import FIXTURE_EVENT_ID
from backend.tests.db_helpers import prepare_test_database


def test_create_opportunities_ignores_duplicate_identity(
    sqlite_database_url: str,
) -> None:
    session_factory, watch_intent_id, market_id = _create_watch_context(
        sqlite_database_url
    )
    first = _make_opportunity(
        opportunity_id="opp-1",
        watch_intent_id=watch_intent_id,
        market_id=market_id,
        sportsbook="DraftKings",
        matched_price=125,
    )
    duplicate = _make_opportunity(
        opportunity_id="opp-2",
        watch_intent_id=watch_intent_id,
        market_id=market_id,
        sportsbook="DraftKings",
        matched_price=130,
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


def test_create_opportunities_allows_different_sportsbooks(
    sqlite_database_url: str,
) -> None:
    session_factory, watch_intent_id, market_id = _create_watch_context(
        sqlite_database_url
    )
    draftkings = _make_opportunity(
        opportunity_id="opp-1",
        watch_intent_id=watch_intent_id,
        market_id=market_id,
        sportsbook="DraftKings",
        matched_price=125,
    )
    fanduel = _make_opportunity(
        opportunity_id="opp-2",
        watch_intent_id=watch_intent_id,
        market_id=market_id,
        sportsbook="FanDuel",
        matched_price=125,
    )

    with SqlAlchemyWatchIntentUnitOfWork(session_factory) as uow:
        inserted = uow.create_opportunities([draftkings, fanduel])

    assert [opp.id for opp in inserted] == ["opp-1", "opp-2"]

    with session_factory.create_session() as session:
        rows = session.execute(select(opportunities_table)).mappings().all()

    assert len(rows) == 2


def test_postgres_create_opportunities_ignores_duplicate_identity() -> None:
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
            sportsbook="DraftKings",
            matched_price=125,
        )
        duplicate = _make_opportunity(
            opportunity_id="opp-2",
            watch_intent_id=watch_intent_id,
            market_id=market_id,
            sportsbook="DraftKings",
            matched_price=130,
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
    sportsbook: str,
    matched_price: int,
) -> Opportunity:
    return Opportunity(
        id=opportunity_id,
        watch_intent_id=watch_intent_id,
        event_id=FIXTURE_EVENT_ID,
        market_id=market_id,
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=121,
        sportsbook=sportsbook,
        matched_price=matched_price,
    )
