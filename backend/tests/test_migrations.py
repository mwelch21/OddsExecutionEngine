import os
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import insert, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.market_identity import build_line_key
from backend.app.infrastructure.persistence.migrations import _build_alembic_config
from backend.app.infrastructure.persistence.schema import (
    events_table,
    market_quotes_history_table,
    market_quotes_latest_table,
    markets_table,
    opportunities_table,
    watch_intents_table,
)


def _seed_market_and_watch(session: Session, created_at: datetime) -> None:
    """One event / market / watch, using only columns that predate 0007."""
    session.execute(
        insert(events_table).values(
            id="event-row-1",
            external_id="event-1",
            starts_at=created_at + timedelta(days=1),
            sport="basketball",
            league="NBA",
        )
    )
    session.execute(
        insert(markets_table).values(
            id="market-1",
            event_id="event-row-1",
            market_type="moneyline",
            selection="knicks",
            line=None,
            line_key=build_line_key(None),
        )
    )
    session.execute(
        insert(watch_intents_table).values(
            id="wi-1",
            event_external_id="event-1",
            market_type="moneyline",
            selection="knicks",
            line=None,
            target_price=120,
        )
    )


def test_one_opportunity_per_watch_migration_wipes_per_book_rows(
    sqlite_database_url: str,
) -> None:
    """The 0007 migration is destructive by design; see its docstring."""
    config = _build_alembic_config(sqlite_database_url)
    command.upgrade(config, "20260510_0006")

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    created_at = datetime.now(UTC)
    with session_factory.create_session() as session:
        _seed_market_and_watch(session, created_at)
        # Raw SQL: these are pre-0007 columns that no longer exist on the mapped table.
        for opportunity_id, sportsbook, price in (
            ("opp-dk", "DraftKings", 125),
            ("opp-fd", "FanDuel", 125),
        ):
            session.execute(
                text(
                    "INSERT INTO opportunities "
                    "(id, watch_intent_id, event_external_id, market_id, "
                    "sportsbook, matched_price, created_at) "
                    "VALUES (:id, 'wi-1', 'event-1', 'market-1', :book, :price, :at)"
                ),
                {
                    "id": opportunity_id,
                    "book": sportsbook,
                    "price": price,
                    "at": created_at,
                },
            )
        session.commit()

    command.upgrade(config, "head")

    with session_factory.create_session() as session:
        rows = session.execute(select(opportunities_table)).mappings().all()

    assert rows == []

    inspector = inspect(session_factory.engine)
    unique_constraints = inspector.get_unique_constraints("opportunities")
    constraint_names = {constraint["name"] for constraint in unique_constraints}
    assert "uq_opportunities_watch_intent" in constraint_names
    assert "uq_opportunities_identity" not in constraint_names


def test_watch_intent_can_hold_at_most_one_opportunity(
    sqlite_database_url: str,
) -> None:
    config = _build_alembic_config(sqlite_database_url)
    command.upgrade(config, "head")

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    with session_factory.create_session() as session:
        _seed_market_and_watch(session, datetime.now(UTC))
        session.execute(
            insert(opportunities_table).values(
                id="opp-1",
                watch_intent_id="wi-1",
                event_external_id="event-1",
                market_id="market-1",
                best_sportsbook="DraftKings",
                best_price=125,
                matching_quotes=[{"sportsbook": "DraftKings", "price": 125}],
            )
        )
        session.commit()

    with session_factory.create_session() as session:
        with pytest.raises(IntegrityError):
            session.execute(
                insert(opportunities_table).values(
                    id="opp-2",
                    watch_intent_id="wi-1",
                    event_external_id="event-1",
                    market_id="market-1",
                    best_sportsbook="FanDuel",
                    best_price=130,
                    matching_quotes=[{"sportsbook": "FanDuel", "price": 130}],
                )
            )
            session.commit()
        session.rollback()

        rows = session.execute(select(opportunities_table)).mappings().all()

    assert [row["id"] for row in rows] == ["opp-1"]


def test_postgres_one_opportunity_per_watch_migration_wipes_per_book_rows() -> None:
    """The same destructive reshape on Postgres.

    SQLite runs `batch_alter_table` by rebuilding the table; Postgres issues native
    ALTERs. Passing on SQLite is no proof the Postgres path is correct.
    """
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    session_factory = DatabaseSessionFactory(database_url)
    with session_factory.engine.begin() as connection:
        for table_name in reversed(inspect(session_factory.engine).get_table_names()):
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table_name} CASCADE")

    config = _build_alembic_config(database_url)
    command.upgrade(config, "20260510_0006")

    created_at = datetime.now(UTC)
    with session_factory.create_session() as session:
        _seed_market_and_watch(session, created_at)
        for opportunity_id, sportsbook, price in (
            ("opp-dk", "DraftKings", 125),
            ("opp-fd", "FanDuel", 125),
        ):
            session.execute(
                text(
                    "INSERT INTO opportunities "
                    "(id, watch_intent_id, event_external_id, market_id, "
                    "sportsbook, matched_price, created_at) "
                    "VALUES (:id, 'wi-1', 'event-1', 'market-1', :book, :price, :at)"
                ),
                {
                    "id": opportunity_id,
                    "book": sportsbook,
                    "price": price,
                    "at": created_at,
                },
            )
        session.commit()

    command.upgrade(config, "head")

    with session_factory.create_session() as session:
        rows = session.execute(select(opportunities_table)).mappings().all()

    assert rows == []

    unique_constraints = inspect(session_factory.engine).get_unique_constraints(
        "opportunities"
    )
    constraint_names = {constraint["name"] for constraint in unique_constraints}
    assert "uq_opportunities_watch_intent" in constraint_names
    assert "uq_opportunities_identity" not in constraint_names


def _insert_pre_0008_quote_rows(session: Session, pulled_at: datetime) -> None:
    """Latest + history rows as 0007 wrote them: one `quoted_at`, holding the pull time."""
    session.execute(
        text(
            "INSERT INTO market_quotes_latest (market_id, sportsbook, price, quoted_at) "
            "VALUES ('market-1', 'DraftKings', 125, :at)"
        ),
        {"at": pulled_at},
    )
    session.execute(
        text(
            "INSERT INTO market_quotes_history (id, market_id, sportsbook, price, quoted_at) "
            "VALUES ('hist-1', 'market-1', 'DraftKings', 125, :at)"
        ),
        {"at": pulled_at},
    )


def _assert_quote_times_were_split(session: Session, pulled_at: datetime) -> None:
    for table in (market_quotes_latest_table, market_quotes_history_table):
        row = session.execute(select(table)).mappings().one()
        assert _as_utc(row["ingested_at"]) == pulled_at, table.name
        # The old value was always the pull time. Keeping it in `quoted_at` would
        # claim the book moved its line at a moment we never observed.
        assert row["quoted_at"] is None, table.name


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def test_quote_time_split_migration_moves_the_pull_time_to_ingested_at(
    sqlite_database_url: str,
) -> None:
    config = _build_alembic_config(sqlite_database_url)
    command.upgrade(config, "20260515_0007")

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    pulled_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    with session_factory.create_session() as session:
        _seed_market_and_watch(session, pulled_at)
        _insert_pre_0008_quote_rows(session, pulled_at)
        session.commit()

    command.upgrade(config, "head")

    with session_factory.create_session() as session:
        _assert_quote_times_were_split(session, pulled_at)


def test_postgres_quote_time_split_migration_moves_the_pull_time_to_ingested_at() -> None:
    """The same reshape on Postgres, which issues native ALTERs instead of a rebuild."""
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    session_factory = DatabaseSessionFactory(database_url)
    with session_factory.engine.begin() as connection:
        for table_name in reversed(inspect(session_factory.engine).get_table_names()):
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table_name} CASCADE")

    config = _build_alembic_config(database_url)
    command.upgrade(config, "20260515_0007")

    pulled_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    with session_factory.create_session() as session:
        _seed_market_and_watch(session, pulled_at)
        _insert_pre_0008_quote_rows(session, pulled_at)
        session.commit()

    command.upgrade(config, "head")

    with session_factory.create_session() as session:
        _assert_quote_times_were_split(session, pulled_at)
