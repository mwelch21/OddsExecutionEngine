"""Quote times survive the round trip: the book's time and the pull time stay apart."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Table, select
from sqlalchemy.engine import RowMapping

from backend.app.domain.models import MarketType, Quote
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.quote_ingestion_uow import (
    SqlAlchemyQuoteIngestionUnitOfWork,
)
from backend.app.infrastructure.persistence.recommendation_uow import (
    SqlAlchemyRecommendationUnitOfWork,
)
from backend.app.infrastructure.persistence.schema import (
    market_quotes_history_table,
    market_quotes_latest_table,
)
from backend.app.infrastructure.persistence.watch_intent_uow import (
    SqlAlchemyWatchIntentUnitOfWork,
)
from backend.tests.db_helpers import prepare_test_database

EVENT_ID = "nba-knicks-celtics-2026-04-11"
MOVED_AT = datetime(2026, 4, 8, 15, 30, tzinfo=UTC)

QUOTE_WITH_BOOK_TIME = Quote(
    event_id=EVENT_ID,
    sportsbook="DraftKings",
    market_type=MarketType.MONEYLINE,
    selection="knicks",
    price=125,
    quoted_at=MOVED_AT,
)
QUOTE_WITHOUT_BOOK_TIME = Quote(
    event_id=EVENT_ID,
    sportsbook="FanDuel",
    market_type=MarketType.MONEYLINE,
    selection="knicks",
    price=120,
)


def _ingest(session_factory: DatabaseSessionFactory, quotes: list[Quote]) -> None:
    with SqlAlchemyQuoteIngestionUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.persist_quotes(EVENT_ID, quotes)


def _rows_by_book(
    session_factory: DatabaseSessionFactory, table: Table
) -> dict[str, RowMapping]:
    with session_factory.create_session() as session:
        rows = session.execute(select(table)).mappings().all()
    return {str(row["sportsbook"]): row for row in rows}


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _assert_times_persisted(session_factory: DatabaseSessionFactory) -> None:
    pulled_around = datetime.now(UTC)
    for table in (market_quotes_latest_table, market_quotes_history_table):
        rows = _rows_by_book(session_factory, table)

        with_book_time = rows["DraftKings"]
        assert _as_utc(with_book_time["quoted_at"]) == MOVED_AT, table.name
        assert (
            pulled_around - _as_utc(with_book_time["ingested_at"]) < timedelta(minutes=1)
        ), table.name

        # No provider time means unknown age. Stamping the pull time here would make a
        # three-day-old line read as seconds old.
        without_book_time = rows["FanDuel"]
        assert without_book_time["quoted_at"] is None, table.name
        assert (
            pulled_around - _as_utc(without_book_time["ingested_at"]) < timedelta(minutes=1)
        ), table.name


def test_ingestion_stores_the_books_time_and_the_pull_time_separately(
    sqlite_database_url: str,
) -> None:
    session_factory = prepare_test_database(sqlite_database_url, seed_demo=False)

    _ingest(session_factory, [QUOTE_WITH_BOOK_TIME, QUOTE_WITHOUT_BOOK_TIME])

    _assert_times_persisted(session_factory)


def test_postgres_ingestion_stores_the_books_time_and_the_pull_time_separately() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    session_factory = prepare_test_database(database_url, seed_demo=False, drop_existing=True)

    _ingest(session_factory, [QUOTE_WITH_BOOK_TIME, QUOTE_WITHOUT_BOOK_TIME])

    _assert_times_persisted(session_factory)


def test_reading_quotes_back_keeps_both_times_apart(sqlite_database_url: str) -> None:
    session_factory = prepare_test_database(sqlite_database_url, seed_demo=False)
    _ingest(session_factory, [QUOTE_WITH_BOOK_TIME, QUOTE_WITHOUT_BOOK_TIME])

    with SqlAlchemyRecommendationUnitOfWork(session_factory) as unit_of_work:
        quotes = {q.sportsbook: q for q in unit_of_work.list_quotes(EVENT_ID)}

    with_book_time = quotes["DraftKings"]
    assert _as_utc_or_none(with_book_time.quoted_at) == MOVED_AT
    assert with_book_time.line_age_known is True
    assert with_book_time.effective_quoted_at == with_book_time.quoted_at

    unknown_age = quotes["FanDuel"]
    assert unknown_age.quoted_at is None
    assert unknown_age.line_age_known is False
    assert unknown_age.effective_quoted_at == unknown_age.ingested_at
    assert unknown_age.ingested_at is not None


def test_watch_evaluation_reads_quotes_with_both_times(sqlite_database_url: str) -> None:
    session_factory = prepare_test_database(sqlite_database_url, seed_demo=False)
    _ingest(session_factory, [QUOTE_WITH_BOOK_TIME, QUOTE_WITHOUT_BOOK_TIME])

    with SqlAlchemyWatchIntentUnitOfWork(session_factory) as unit_of_work:
        quotes = {q.sportsbook: q for q in unit_of_work.list_quotes(EVENT_ID)}

    assert _as_utc_or_none(quotes["DraftKings"].quoted_at) == MOVED_AT
    assert quotes["FanDuel"].quoted_at is None
    assert quotes["FanDuel"].ingested_at is not None


def _as_utc_or_none(value: datetime | None) -> datetime | None:
    return None if value is None else _as_utc(value)
