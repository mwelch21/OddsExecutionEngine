from datetime import datetime
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


class PersistedQuote(DomainModel):
    quote: Quote
    market_id: str
    market_created: bool


class QuoteRefreshPersistenceResult(DomainModel):
    event_id: str
    persisted_quotes: list[PersistedQuote]
    created_market_count: int
    updated_latest_count: int
    appended_history_count: int


class QuoteRefreshSummary(DomainModel):
    event_id: str
    ingested_quote_count: int
    created_market_count: int
    updated_latest_count: int
    appended_history_count: int
    emitted_event_types: list[str]


class ExecutionRecommendation(DomainModel):
    intent: OrderIntent
    fillable: bool
    best_quote: Quote | None
    ranked_quotes: list[Quote]
    nearest_miss: Quote | None
    matched_quote_count: int


class WatchIntent(DomainModel):
    id: str
    event_id: str
    market_type: MarketType
    selection: str
    target_price: int
    line: float | None = None
    status: str = "active"
    created_at: datetime | None = None


class Opportunity(DomainModel):
    id: str
    watch_intent_id: str
    event_id: str
    market_id: str
    market_type: MarketType
    selection: str
    target_price: int
    sportsbook: str
    matched_price: int
    line: float | None = None
    created_at: datetime | None = None


class OpportunityWithValidity(DomainModel):
    opportunity: Opportunity
    is_valid: bool
    reason: str | None = None


class WatchEvaluationResult(DomainModel):
    watch_intent: WatchIntent
    opportunities: list[Opportunity]
