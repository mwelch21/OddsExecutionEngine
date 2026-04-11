from dataclasses import dataclass
from enum import StrEnum


class MarketType(StrEnum):
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    event_id: str
    market_type: MarketType
    selection: str
    target_price: int
    line: float | None = None


@dataclass(frozen=True, slots=True)
class Quote:
    event_id: str
    sportsbook: str
    market_type: MarketType
    selection: str
    price: int
    line: float | None = None


@dataclass(frozen=True, slots=True)
class ExecutionRecommendation:
    intent: OrderIntent
    fillable: bool
    best_quote: Quote | None
    ranked_quotes: list[Quote]
    nearest_miss: Quote | None
    matched_quote_count: int
