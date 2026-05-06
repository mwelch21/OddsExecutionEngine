from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import insert, inspect, select
from sqlalchemy.exc import IntegrityError

from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.market_identity import build_line_key
from backend.app.infrastructure.persistence.migrations import _build_alembic_config
from backend.app.infrastructure.persistence.schema import (
    events_table,
    markets_table,
    opportunities_table,
    watch_intents_table,
)


def test_opportunity_identity_migration_dedupes_existing_rows(
    sqlite_database_url: str,
) -> None:
    config = _build_alembic_config(sqlite_database_url)
    command.upgrade(config, "20260420_0004")

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    created_at = datetime.now(UTC)
    with session_factory.create_session() as session:
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
        session.execute(
            insert(opportunities_table).values(
                id="opp-keep",
                watch_intent_id="wi-1",
                event_external_id="event-1",
                market_id="market-1",
                sportsbook="DraftKings",
                matched_price=125,
                created_at=created_at,
            )
        )
        session.execute(
            insert(opportunities_table).values(
                id="opp-drop",
                watch_intent_id="wi-1",
                event_external_id="event-1",
                market_id="market-1",
                sportsbook="DraftKings",
                matched_price=130,
                created_at=created_at + timedelta(minutes=1),
            )
        )
        session.commit()

    command.upgrade(config, "head")

    with session_factory.create_session() as session:
        rows = session.execute(select(opportunities_table)).mappings().all()

    assert len(rows) == 1
    assert rows[0]["id"] == "opp-keep"

    inspector = inspect(session_factory.engine)
    unique_constraints = inspector.get_unique_constraints("opportunities")
    assert any(
        constraint["name"] == "uq_opportunities_identity"
        for constraint in unique_constraints
    )

    with session_factory.create_session() as session:
        with pytest.raises(IntegrityError):
            session.execute(
                insert(opportunities_table).values(
                    id="opp-again",
                    watch_intent_id="wi-1",
                    event_external_id="event-1",
                    market_id="market-1",
                    sportsbook="DraftKings",
                    matched_price=140,
                )
            )
            session.commit()
        session.rollback()

        rows = session.execute(select(opportunities_table)).mappings().all()

    assert len(rows) == 1
