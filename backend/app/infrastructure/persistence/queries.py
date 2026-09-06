from datetime import UTC, datetime

from sqlalchemy import RowMapping, Select, select

from backend.app.domain.models import (
    MarketType,
    OpportunitySignal,
    Quote,
    WatchIntent,
    WatchStatus,
)
from backend.app.infrastructure.persistence.schema import (
    events_table,
    market_quotes_latest_table,
    markets_table,
)


def select_latest_quotes(event_id: str) -> Select[tuple[str, str, str, str, int, float | None]]:
    return (
        select(
            events_table.c.external_id.label("event_id"),
            market_quotes_latest_table.c.sportsbook,
            markets_table.c.market_type,
            markets_table.c.selection,
            market_quotes_latest_table.c.price,
            markets_table.c.line,
        )
        .select_from(
            market_quotes_latest_table.join(
                markets_table,
                market_quotes_latest_table.c.market_id == markets_table.c.id,
            ).join(events_table, markets_table.c.event_id == events_table.c.id)
        )
        .where(events_table.c.external_id == event_id)
    )


def row_to_quote(row: RowMapping) -> Quote:
    return Quote(
        event_id=row["event_id"],
        sportsbook=row["sportsbook"],
        market_type=MarketType(row["market_type"]),
        selection=row["selection"],
        price=row["price"],
        line=row["line"],
    )


def row_to_watch_intent(row: RowMapping) -> WatchIntent:
    return WatchIntent(
        id=row["id"],
        event_id=row["event_external_id"],
        market_type=MarketType(row["market_type"]),
        selection=row["selection"],
        target_price=row["target_price"],
        line=row["line"],
        expires_at=as_utc(row["expires_at"]),
        status=WatchStatus(row["status"]),
        created_at=_require_utc(row["created_at"]),
    )


def row_to_opportunity_signal(row: RowMapping) -> OpportunitySignal:
    return OpportunitySignal(
        id=row["id"],
        watch_intent_id=row["watch_intent_id"],
        event_id=row["event_external_id"],
        market_type=MarketType(row["market_type"]),
        selection=row["selection"],
        line=row["line"],
        matched_price=row["matched_price"],
        target_price=row["target_price"],
        sportsbook=row["sportsbook"],
        created_at=_require_utc(row["created_at"]),
    )


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)


def _require_utc(value: datetime) -> datetime:
    normalized = as_utc(value)
    if normalized is None:
        raise ValueError("Expected a non-null timestamp value.")
    return normalized
