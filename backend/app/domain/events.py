from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from backend.app.domain.base import DomainModel
from backend.app.domain.models import ExecutionRecommendation, OrderIntent, Quote


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


class OrderIntentSubmitted(WorkflowEvent):
    event_type: Literal["OrderIntentSubmitted"] = "OrderIntentSubmitted"
    payload: OrderIntentSubmittedPayload


class ExecutionRecommendationGenerated(WorkflowEvent):
    event_type: Literal["ExecutionRecommendationGenerated"] = (
        "ExecutionRecommendationGenerated"
    )
    payload: ExecutionRecommendationGeneratedPayload


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


def _quote_snapshot(quote: Quote | None) -> QuoteSnapshot | None:
    if quote is None:
        return None

    return QuoteSnapshot(
        sportsbook=quote.sportsbook,
        selection=quote.selection,
        price=quote.price,
        line=quote.line,
    )
