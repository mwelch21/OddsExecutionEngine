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


class WatchStatus(StrEnum):
    ACTIVE = "active"
    TRIGGERED = "triggered"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class WatchIntentDraft(DomainModel):
    event_id: str
    market_type: MarketType
    selection: str
    target_price: int
    line: float | None = None
    expires_at: datetime | None = None


class WatchIntent(DomainModel):
    id: str
    event_id: str
    market_type: MarketType
    selection: str
    target_price: int
    line: float | None = None
    expires_at: datetime | None = None
    status: WatchStatus
    created_at: datetime


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


class OpportunitySignal(DomainModel):
    id: str
    watch_intent_id: str
    event_id: str
    market_type: MarketType
    selection: str
    line: float | None = None
    matched_price: int
    target_price: int
    sportsbook: str
    created_at: datetime


class TriggeredWatch(DomainModel):
    watch_intent: WatchIntent
    quote: Quote


class WatchEvaluationResult(DomainModel):
    triggered: list[TriggeredWatch]
    expired: list[WatchIntent]


class WatchEvaluationSummary(DomainModel):
    event_id: str
    evaluated_watch_count: int
    triggered_watch_count: int
    expired_watch_count: int
    emitted_event_types: list[str]


class ExecutionRecommendation(DomainModel):
    intent: OrderIntent
    fillable: bool
    best_quote: Quote | None
    ranked_quotes: list[Quote]
    nearest_miss: Quote | None
    matched_quote_count: int
