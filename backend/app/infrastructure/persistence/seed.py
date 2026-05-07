from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.domain.models import Quote
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.market_identity import build_line_key
from backend.app.infrastructure.persistence.schema import (
    event_participants_table,
    events_table,
    execution_recommendations_table,
    market_quotes_history_table,
    market_quotes_latest_table,
    markets_table,
    opportunities_table,
    order_intents_table,
    watch_intents_table,
    workflow_events_table,
)
from backend.app.infrastructure.quote_provider import FIXTURE_EVENT_ID, build_fixture_quotes


def seed_demo_database(database_url: str | None = None) -> None:
    target_url = database_url or Settings().database_url
    seed_demo_quotes(DatabaseSessionFactory(target_url))


def seed_demo_quotes(session_factory: DatabaseSessionFactory) -> None:
    with session_factory.create_session() as session:
        latest_quote_exists = session.execute(
            select(market_quotes_latest_table.c.market_id)
        ).first()
        if latest_quote_exists is not None:
            return

        _seed_fixture_quotes(session, build_fixture_quotes())
        session.commit()


def truncate_application_tables(session_factory: DatabaseSessionFactory) -> None:
    with session_factory.create_session() as session:
        for table in (
            opportunities_table,
            watch_intents_table,
            workflow_events_table,
            execution_recommendations_table,
            order_intents_table,
            market_quotes_history_table,
            market_quotes_latest_table,
            markets_table,
            event_participants_table,
            events_table,
        ):
            session.execute(table.delete())
        session.commit()


def _seed_fixture_quotes(session: Session, quotes: list[Quote]) -> None:
    now = datetime.now(UTC)
    event_ids: dict[str, str] = {}
    market_ids: dict[tuple[str, str, str, float | None], str] = {}

    for quote in quotes:
        if quote.event_id not in event_ids:
            event_ids[quote.event_id] = str(uuid4())
            session.execute(
                insert(events_table).values(
                    id=event_ids[quote.event_id],
                    external_id=quote.event_id,
                    starts_at=now + timedelta(days=3),
                    sport="basketball",
                    league="NBA",
                )
            )
            if quote.event_id == FIXTURE_EVENT_ID:
                for p in [
                    {"name": "Celtics", "role": "team", "side": "home", "sort_order": 1},
                    {"name": "Knicks", "role": "team", "side": "away", "sort_order": 2},
                ]:
                    session.execute(
                        insert(event_participants_table).values(
                            id=str(uuid4()),
                            event_id=event_ids[quote.event_id],
                            participant_name=p["name"],
                            role=p["role"],
                            side=p["side"],
                            sort_order=p["sort_order"],
                        )
                    )

        market_key = (
            quote.event_id,
            quote.market_type.value,
            quote.selection,
            quote.line,
        )
        if market_key not in market_ids:
            market_ids[market_key] = str(uuid4())
            session.execute(
                insert(markets_table).values(
                    id=market_ids[market_key],
                    event_id=event_ids[quote.event_id],
                    market_type=quote.market_type.value,
                    selection=quote.selection,
                    line=quote.line,
                    line_key=build_line_key(quote.line),
                )
            )

        market_id = market_ids[market_key]
        session.execute(
            insert(market_quotes_latest_table).values(
                market_id=market_id,
                sportsbook=quote.sportsbook,
                price=quote.price,
                quoted_at=now,
            )
        )
        session.execute(
            insert(market_quotes_history_table).values(
                id=str(uuid4()),
                market_id=market_id,
                sportsbook=quote.sportsbook,
                price=quote.price,
                quoted_at=now,
            )
        )
