from datetime import UTC, datetime
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


class WatchStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class WatchIntent(DomainModel):
    id: str
    event_id: str
    market_type: MarketType
    selection: str
    target_price: int
    line: float | None = None
    expires_at: datetime | None = None
    status: WatchStatus = WatchStatus.ACTIVE
    created_at: datetime | None = None

    def is_expired_at(self, now: datetime) -> bool:
        """True once the watch's TTL has passed. Never evaluated again after this."""
        if self.expires_at is None:
            return False

        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        return expires_at <= now

    def effective_status(self, now: datetime) -> WatchStatus:
        """Status a reader should see.

        Expiry is applied when an event is next evaluated, so a watch whose TTL passed
        while no quotes refreshed is still stored as `active`. It can never produce an
        opportunity, so reads must not present it as live.
        """
        if self.status is WatchStatus.ACTIVE and self.is_expired_at(now):
            return WatchStatus.EXPIRED

        return self.status

    def with_effective_status(self, now: datetime) -> "WatchIntent":
        status = self.effective_status(now)
        if status is self.status:
            return self

        return self.model_copy(update={"status": status})


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


class EventParticipant(DomainModel):
    name: str
    role: str = "team"
    side: str | None = None
    sort_order: int = 0


class EventInfo(DomainModel):
    id: str
    sport: str
    league: str | None = None
    status: str = "upcoming"
    participants: list[EventParticipant] = []
    commence_time: datetime | None = None
