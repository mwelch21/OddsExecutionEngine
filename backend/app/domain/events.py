from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from backend.app.domain.base import DomainModel
from backend.app.domain.models import (
    ExecutionRecommendation,
    Opportunity,
    OrderIntent,
    PersistedQuote,
    Quote,
    QuoteRefreshPersistenceResult,
    WatchIntent,
)


class WorkflowEvent(DomainModel):
    id: str
    event_type: str
    occurred_at: datetime
    aggregate_id: str
    workflow_id: str
    payload: DomainModel


class QuoteSnapshot(DomainModel):
    sportsbook: str
    selection: str
    price: int
    line: float | None = None


class OrderIntentSubmittedPayload(DomainModel):
    event_id: str
    market_type: str
    selection: str
    target_price: int
    line: float | None = None


class ExecutionRecommendationGeneratedPayload(DomainModel):
    fillable: bool
    matched_quote_count: int
    best_quote: QuoteSnapshot | None
    nearest_miss: QuoteSnapshot | None


class QuotesRefreshedPayload(DomainModel):
    event_id: str
    ingested_quote_count: int
    created_market_count: int
    updated_latest_count: int
    appended_history_count: int


class QuoteUpdatedPayload(DomainModel):
    event_id: str
    market_type: str
    selection: str
    sportsbook: str
    price: int
    line: float | None = None


class MarketSnapshotCreatedPayload(DomainModel):
    event_id: str
    market_type: str
    selection: str
    line: float | None = None


class OrderIntentSubmitted(WorkflowEvent):
    event_type: Literal["OrderIntentSubmitted"] = "OrderIntentSubmitted"
    payload: OrderIntentSubmittedPayload


class ExecutionRecommendationGenerated(WorkflowEvent):
    event_type: Literal["ExecutionRecommendationGenerated"] = (
        "ExecutionRecommendationGenerated"
    )
    payload: ExecutionRecommendationGeneratedPayload


class QuotesRefreshed(WorkflowEvent):
    event_type: Literal["QuotesRefreshed"] = "QuotesRefreshed"
    payload: QuotesRefreshedPayload


class QuoteUpdated(WorkflowEvent):
    event_type: Literal["QuoteUpdated"] = "QuoteUpdated"
    payload: QuoteUpdatedPayload


class MarketSnapshotCreated(WorkflowEvent):
    event_type: Literal["MarketSnapshotCreated"] = "MarketSnapshotCreated"
    payload: MarketSnapshotCreatedPayload


def build_order_intent_submitted_event(
    *,
    order_intent_id: str,
    intent: OrderIntent,
) -> OrderIntentSubmitted:
    return OrderIntentSubmitted(
        id=str(uuid4()),
        occurred_at=datetime.now(UTC),
        aggregate_id=order_intent_id,
        workflow_id=order_intent_id,
        payload=OrderIntentSubmittedPayload(
            event_id=intent.event_id,
            market_type=intent.market_type.value,
            selection=intent.selection,
            target_price=intent.target_price,
            line=intent.line,
        ),
    )


def build_execution_recommendation_generated_event(
    *,
    order_intent_id: str,
    recommendation_id: str,
    recommendation: ExecutionRecommendation,
) -> ExecutionRecommendationGenerated:
    return ExecutionRecommendationGenerated(
        id=str(uuid4()),
        occurred_at=datetime.now(UTC),
        aggregate_id=recommendation_id,
        workflow_id=order_intent_id,
        payload=ExecutionRecommendationGeneratedPayload(
            fillable=recommendation.fillable,
            matched_quote_count=recommendation.matched_quote_count,
            best_quote=_quote_snapshot(recommendation.best_quote),
            nearest_miss=_quote_snapshot(recommendation.nearest_miss),
        ),
    )


def build_quotes_refreshed_event(
    *,
    refresh_id: str,
    result: QuoteRefreshPersistenceResult,
) -> QuotesRefreshed:
    return QuotesRefreshed(
        id=str(uuid4()),
        occurred_at=datetime.now(UTC),
        aggregate_id=refresh_id,
        workflow_id=refresh_id,
        payload=QuotesRefreshedPayload(
            event_id=result.event_id,
            ingested_quote_count=len(result.persisted_quotes),
            created_market_count=result.created_market_count,
            updated_latest_count=result.updated_latest_count,
            appended_history_count=result.appended_history_count,
        ),
    )


def build_quote_updated_event(
    *,
    refresh_id: str,
    persisted_quote: PersistedQuote,
) -> QuoteUpdated:
    return QuoteUpdated(
        id=str(uuid4()),
        occurred_at=datetime.now(UTC),
        aggregate_id=persisted_quote.market_id,
        workflow_id=refresh_id,
        payload=QuoteUpdatedPayload(
            event_id=persisted_quote.quote.event_id,
            market_type=persisted_quote.quote.market_type.value,
            selection=persisted_quote.quote.selection,
            sportsbook=persisted_quote.quote.sportsbook,
            price=persisted_quote.quote.price,
            line=persisted_quote.quote.line,
        ),
    )


def build_market_snapshot_created_event(
    *,
    refresh_id: str,
    persisted_quote: PersistedQuote,
) -> MarketSnapshotCreated:
    return MarketSnapshotCreated(
        id=str(uuid4()),
        occurred_at=datetime.now(UTC),
        aggregate_id=persisted_quote.market_id,
        workflow_id=refresh_id,
        payload=MarketSnapshotCreatedPayload(
            event_id=persisted_quote.quote.event_id,
            market_type=persisted_quote.quote.market_type.value,
            selection=persisted_quote.quote.selection,
            line=persisted_quote.quote.line,
        ),
    )


class WatchIntentCreatedPayload(DomainModel):
    event_id: str
    market_type: str
    selection: str
    target_price: int
    line: float | None = None


class WatchIntentCancelledPayload(DomainModel):
    event_id: str
    market_type: str
    selection: str


class OpportunityIdentifiedPayload(DomainModel):
    watch_intent_id: str
    event_id: str
    market_type: str
    selection: str
    sportsbook: str
    matched_price: int
    target_price: int
    line: float | None = None


class WatchIntentCreated(WorkflowEvent):
    event_type: Literal["WatchIntentCreated"] = "WatchIntentCreated"
    payload: WatchIntentCreatedPayload


class WatchIntentExpiredPayload(DomainModel):
    watch_intent_id: str
    event_id: str
    expires_at: datetime | None = None


class WatchIntentExpired(WorkflowEvent):
    event_type: Literal["WatchIntentExpired"] = "WatchIntentExpired"
    payload: WatchIntentExpiredPayload


class WatchIntentCancelled(WorkflowEvent):
    event_type: Literal["WatchIntentCancelled"] = "WatchIntentCancelled"
    payload: WatchIntentCancelledPayload


class OpportunityIdentified(WorkflowEvent):
    event_type: Literal["OpportunityIdentified"] = "OpportunityIdentified"
    payload: OpportunityIdentifiedPayload


def build_watch_intent_created_event(
    *,
    watch_intent_id: str,
    intent: WatchIntent,
) -> WatchIntentCreated:
    return WatchIntentCreated(
        id=str(uuid4()),
        occurred_at=datetime.now(UTC),
        aggregate_id=watch_intent_id,
        workflow_id=watch_intent_id,
        payload=WatchIntentCreatedPayload(
            event_id=intent.event_id,
            market_type=intent.market_type.value,
            selection=intent.selection,
            target_price=intent.target_price,
            line=intent.line,
        ),
    )


def build_watch_intent_cancelled_event(
    *,
    watch_intent_id: str,
    intent: WatchIntent,
) -> WatchIntentCancelled:
    return WatchIntentCancelled(
        id=str(uuid4()),
        occurred_at=datetime.now(UTC),
        aggregate_id=watch_intent_id,
        workflow_id=watch_intent_id,
        payload=WatchIntentCancelledPayload(
            event_id=intent.event_id,
            market_type=intent.market_type.value,
            selection=intent.selection,
        ),
    )


def build_watch_intent_expired_event(
    *,
    watch_intent_id: str,
    intent: WatchIntent,
) -> WatchIntentExpired:
    return WatchIntentExpired(
        id=str(uuid4()),
        occurred_at=datetime.now(UTC),
        aggregate_id=watch_intent_id,
        workflow_id=watch_intent_id,
        payload=WatchIntentExpiredPayload(
            watch_intent_id=watch_intent_id,
            event_id=intent.event_id,
            expires_at=intent.expires_at,
        ),
    )


def build_opportunity_identified_event(
    *,
    watch_intent_id: str,
    opportunity: Opportunity,
) -> OpportunityIdentified:
    return OpportunityIdentified(
        id=str(uuid4()),
        occurred_at=datetime.now(UTC),
        aggregate_id=opportunity.id,
        workflow_id=watch_intent_id,
        payload=OpportunityIdentifiedPayload(
            watch_intent_id=watch_intent_id,
            event_id=opportunity.event_id,
            market_type=opportunity.market_type.value,
            selection=opportunity.selection,
            sportsbook=opportunity.sportsbook,
            matched_price=opportunity.matched_price,
            target_price=opportunity.target_price,
            line=opportunity.line,
        ),
    )


def _quote_snapshot(quote: Quote | None) -> QuoteSnapshot | None:
    if quote is None:
        return None

    return QuoteSnapshot(
        sportsbook=quote.sportsbook,
        selection=quote.selection,
        price=quote.price,
        line=quote.line,
    )
