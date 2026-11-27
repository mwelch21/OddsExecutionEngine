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


def _seed_market_and_watch(
    session: Session, created_at: datetime, **watch_columns: object
) -> None:
    """One event / market / watch, using only columns that predate 0007.

    `watch_columns` adds later watch columns when the test runs at a later revision.
    """
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
            **watch_columns,
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
        _seed_market_and_watch(session, datetime.now(UTC), watch_window="pre_game")
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


def _reset_postgres(database_url: str) -> DatabaseSessionFactory:
    session_factory = DatabaseSessionFactory(database_url)
    with session_factory.engine.begin() as connection:
        for table_name in reversed(inspect(session_factory.engine).get_table_names()):
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table_name} CASCADE")
    return session_factory


def _assert_call_outcome_migration(
    database_url: str, session_factory: DatabaseSessionFactory
) -> None:
    config = _build_alembic_config(database_url)
    command.upgrade(config, "20261108_0016")
    with session_factory.create_session() as session:
        session.execute(
            text(
                "INSERT INTO quota_observations (remaining, used, source, out_of_credits,"
                " observed_at, call_kind) VALUES (400, 100, 'headers', false, :at, 'sport')"
            ),
            {"at": datetime(2026, 11, 8, 12, 0, tzinfo=UTC)},
        )
        session.commit()

    command.upgrade(config, "20261109_0017")

    with session_factory.create_session() as session:
        # How a call stored before this revision ended was never kept: it stays null.
        assert session.execute(text("SELECT call_outcome FROM quota_observations")).all() == [
            (None,)
        ]
        with pytest.raises(IntegrityError):
            session.execute(text("UPDATE quota_observations SET call_outcome = 'fine'"))
        session.rollback()

    command.downgrade(config, "20261108_0016")
    columns = {
        column["name"]
        for column in inspect(session_factory.engine).get_columns("quota_observations")
    }
    assert "call_outcome" not in columns
    command.upgrade(config, "head")


def test_call_outcome_migration_keeps_stored_calls_unknown(sqlite_database_url: str) -> None:
    _assert_call_outcome_migration(sqlite_database_url, DatabaseSessionFactory(sqlite_database_url))


def test_postgres_call_outcome_migration_keeps_stored_calls_unknown() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    _assert_call_outcome_migration(database_url, _reset_postgres(database_url))


def _assert_event_status_line_phase_migration(
    database_url: str, session_factory: DatabaseSessionFactory
) -> None:
    config = _build_alembic_config(database_url)
    command.upgrade(config, "20261109_0017")
    kickoff = datetime(2026, 11, 20, 20, 0, tzinfo=UTC)
    with session_factory.create_session() as session:
        _seed_market_and_watch(session, kickoff - timedelta(days=1))
        for table in ("market_quotes_latest", "market_quotes_history"):
            for sportsbook, pulled_at in (
                ("DraftKings", kickoff - timedelta(hours=1)),
                ("FanDuel", kickoff + timedelta(minutes=30)),
            ):
                id_column = "id, " if table == "market_quotes_history" else ""
                id_value = f"'{table}-{sportsbook}', " if id_column else ""
                session.execute(
                    text(
                        f"INSERT INTO {table} ({id_column}market_id, sportsbook, price,"  # noqa: S608
                        f" ingested_at) VALUES ({id_value}'market-1', :book, 120, :at)"
                    ),
                    {"book": sportsbook, "at": pulled_at},
                )
        session.commit()

    command.upgrade(config, "20261127_0018")

    with session_factory.create_session() as session:
        for table in ("market_quotes_latest", "market_quotes_history"):
            rows = session.execute(
                text(f"SELECT sportsbook, phase FROM {table}")  # noqa: S608
            ).all()
            phases = {str(row[0]): str(row[1]) for row in rows}
            # Pulled after kickoff from a feed that still offered it: live.
            assert phases == {"DraftKings": "pre_game", "FanDuel": "live"}, table
        # Whether the stored event is live or ended was never observed: unchanged.
        assert session.execute(text("SELECT status FROM events")).scalar_one() == "upcoming"
        assert session.execute(text("SELECT status_observed_at FROM events")).scalar_one() is None
        with pytest.raises(IntegrityError):
            session.execute(text("UPDATE events SET status = 'halftime'"))
        session.rollback()
        with pytest.raises(IntegrityError):
            session.execute(text("UPDATE market_quotes_latest SET phase = 'overtime'"))
        session.rollback()

    command.downgrade(config, "20261109_0017")
    for table in ("market_quotes_latest", "market_quotes_history"):
        columns = {c["name"] for c in inspect(session_factory.engine).get_columns(table)}
        assert "phase" not in columns, table
    event_columns = {c["name"] for c in inspect(session_factory.engine).get_columns("events")}
    assert "status_observed_at" not in event_columns
    command.upgrade(config, "head")


def test_event_status_line_phase_migration_backfills_phase_from_kickoff(
    sqlite_database_url: str,
) -> None:
    _assert_event_status_line_phase_migration(
        sqlite_database_url, DatabaseSessionFactory(sqlite_database_url)
    )


def test_postgres_event_status_line_phase_migration_backfills_phase_from_kickoff() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    _assert_event_status_line_phase_migration(database_url, _reset_postgres(database_url))


def _assert_watch_window_migration(
    database_url: str, session_factory: DatabaseSessionFactory
) -> None:
    config = _build_alembic_config(database_url)
    command.upgrade(config, "20261127_0018")
    kickoff = datetime(2026, 11, 20, 20, 0, tzinfo=UTC)
    with session_factory.create_session() as session:
        # The event starts a day after `created_at`: kickoff.
        _seed_market_and_watch(session, kickoff - timedelta(days=1))
        session.execute(
            text(
                "INSERT INTO watch_intents (id, event_external_id, market_type, selection,"
                " target_price, status) VALUES"
                " ('wi-expired', 'event-1', 'moneyline', 'knicks', 120, 'expired'),"
                " ('wi-live', 'event-1', 'moneyline', 'knicks', 120, 'triggered')"
            )
        )
        for opportunity_id, watch_id, created_at in (
            ("opp-pre", "wi-1", kickoff - timedelta(hours=1)),
            ("opp-live", "wi-live", kickoff + timedelta(minutes=30)),
        ):
            session.execute(
                text(
                    "INSERT INTO opportunities (id, watch_intent_id, event_external_id,"
                    " market_id, best_sportsbook, best_price, matching_quotes, created_at)"
                    " VALUES (:id, :watch, 'event-1', 'market-1', 'DraftKings', 125, '[]', :at)"
                ),
                {"id": opportunity_id, "watch": watch_id, "at": created_at},
            )
        session.commit()

    command.upgrade(config, "20261127_0019")

    with session_factory.create_session() as session:
        rows = session.execute(
            text("SELECT id, watch_window, expired_reason FROM watch_intents")
        ).all()
        # Every stored watch did what pre_game means; only a TTL could expire one.
        assert {str(r[0]): (str(r[1]), r[2]) for r in rows} == {
            "wi-1": ("pre_game", None),
            "wi-expired": ("pre_game", "ttl"),
            "wi-live": ("pre_game", None),
        }
        phases = dict(
            session.execute(text("SELECT id, phase FROM opportunities")).tuples().all()
        )
        assert phases == {"opp-pre": "pre_game", "opp-live": "live"}

        # The policy is the only default: an insert must name its window.
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO watch_intents (id, event_external_id, market_type,"
                    " selection, target_price) VALUES ('wi-x', 'event-1', 'moneyline',"
                    " 'knicks', 120)"
                )
            )
        session.rollback()
        for statement in (
            "UPDATE watch_intents SET watch_window = 'halftime'",
            "UPDATE watch_intents SET expired_reason = 'bored' WHERE id = 'wi-expired'",
            # A reason belongs to an expired watch only, and an expired one has one.
            "UPDATE watch_intents SET expired_reason = 'ttl' WHERE id = 'wi-1'",
            "UPDATE watch_intents SET expired_reason = NULL WHERE id = 'wi-expired'",
            "UPDATE opportunities SET phase = 'overtime'",
        ):
            with pytest.raises(IntegrityError):
                session.execute(text(statement))
            session.rollback()

    command.downgrade(config, "20261127_0018")
    inspector = inspect(session_factory.engine)
    watch_columns = {c["name"] for c in inspector.get_columns("watch_intents")}
    assert not {"watch_window", "expired_reason"} & watch_columns
    assert "phase" not in {c["name"] for c in inspector.get_columns("opportunities")}
    command.upgrade(config, "head")


def test_watch_window_migration_backfills_pre_game_and_ttl(sqlite_database_url: str) -> None:
    _assert_watch_window_migration(
        sqlite_database_url, DatabaseSessionFactory(sqlite_database_url)
    )


def test_postgres_watch_window_migration_backfills_pre_game_and_ttl() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    _assert_watch_window_migration(database_url, _reset_postgres(database_url))
