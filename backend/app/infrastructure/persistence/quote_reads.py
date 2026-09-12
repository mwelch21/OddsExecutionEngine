"""Shared read of the latest quote per book.

Recommendation and watch evaluation ask the same question of the same tables, and
a quote answered differently by the two paths is a quote the system disagrees with
itself about — including on which clock its age comes from.
"""

from sqlalchemy import RowMapping, select
from sqlalchemy.orm import Session

from backend.app.domain.models import MarketType, Quote
from backend.app.infrastructure.persistence.schema import (
    events_table,
    market_quotes_latest_table,
    markets_table,
)


def list_latest_quotes(session: Session, event_id: str) -> list[Quote]:
    rows = session.execute(
        select(
            events_table.c.external_id.label("event_id"),
            market_quotes_latest_table.c.sportsbook,
            markets_table.c.market_type,
            markets_table.c.selection,
            market_quotes_latest_table.c.price,
            markets_table.c.line,
            market_quotes_latest_table.c.quoted_at,
            market_quotes_latest_table.c.ingested_at,
        )
        .select_from(
            market_quotes_latest_table.join(
                markets_table,
                market_quotes_latest_table.c.market_id == markets_table.c.id,
            ).join(events_table, markets_table.c.event_id == events_table.c.id)
        )
        .where(events_table.c.external_id == event_id)
    )
    return [_row_to_quote(row) for row in rows.mappings().all()]


def _row_to_quote(row: RowMapping) -> Quote:
    return Quote(
        event_id=row["event_id"],
        sportsbook=row["sportsbook"],
        market_type=MarketType(row["market_type"]),
        selection=row["selection"],
        price=row["price"],
        line=row["line"],
        quoted_at=row["quoted_at"],
        ingested_at=row["ingested_at"],
    )
