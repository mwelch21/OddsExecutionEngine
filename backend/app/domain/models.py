from enum import StrEnum

from backend.app.domain.base import DomainModel


class MarketType(StrEnum):
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"


class OrderIntent(DomainModel):
    event_id: str
    market_type: MarketType
    selection: str
    target_price: int
    line: float | None = None


class Quote(DomainModel):
    event_id: str
    sportsbook: str
    market_type: MarketType
    selection: str
    price: int
    line: float | None = None


class ExecutionRecommendation(DomainModel):
    intent: OrderIntent
    fillable: bool
    best_quote: Quote | None
    ranked_quotes: list[Quote]
    nearest_miss: Quote | None
    matched_quote_count: int
