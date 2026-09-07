from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from backend.app.api.opportunity_schemas import MatchingQuoteResponse
from backend.app.domain.models import (
    MarketType,
    Opportunity,
    WatchIntent,
    WatchIntentCreationResult,
    WatchStatus,
)


class CreateWatchIntentRequest(BaseModel):
    event_id: str = Field(min_length=1)
    market_type: MarketType
    selection: str = Field(min_length=1)
    line: float | None = None
    target_price: int
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_market_fields(self) -> "CreateWatchIntentRequest":
        if self.market_type is MarketType.MONEYLINE and self.line is not None:
            raise ValueError("line must be omitted for moneyline requests")

        if self.market_type in {MarketType.SPREAD, MarketType.TOTAL} and self.line is None:
            raise ValueError("line is required for spread and total requests")

        if self.market_type is MarketType.TOTAL and self.selection not in {"over", "under"}:
            raise ValueError("selection must be 'over' or 'under' for total requests")

        return self


class WatchIntentResponse(BaseModel):
    id: str
    event_id: str
    market_type: MarketType
    selection: str
    target_price: int
    line: float | None
    expires_at: datetime | None
    status: WatchStatus
    created_at: datetime | None

    @classmethod
    def from_domain(cls, intent: WatchIntent) -> "WatchIntentResponse":
        return cls(
            id=intent.id,
            event_id=intent.event_id,
            market_type=intent.market_type,
            selection=intent.selection,
            target_price=intent.target_price,
            line=intent.line,
            expires_at=intent.expires_at,
            status=intent.status,
            created_at=intent.created_at,
        )


class IdentifiedOpportunityResponse(BaseModel):
    """The opportunity a watch filled on creation.

    No `is_valid` flag: this is what was true in the transaction that just
    committed, so a freshness check here would be answering a question nobody
    asked. Re-read `GET /opportunities/{id}` for that.
    """

    id: str
    best_sportsbook: str
    best_price: int
    matching_quotes: list[MatchingQuoteResponse]

    @classmethod
    def from_domain(cls, opportunity: Opportunity) -> "IdentifiedOpportunityResponse":
        return cls(
            id=opportunity.id,
            best_sportsbook=opportunity.best_sportsbook,
            best_price=opportunity.best_price,
            matching_quotes=[
                MatchingQuoteResponse(sportsbook=quote.sportsbook, price=quote.price)
                for quote in opportunity.matching_quotes
            ],
        )


class CreateWatchIntentResponse(WatchIntentResponse):
    """A created watch, plus the opportunity if it filled immediately."""

    opportunity: IdentifiedOpportunityResponse | None = None

    @classmethod
    def from_creation(
        cls, result: WatchIntentCreationResult
    ) -> "CreateWatchIntentResponse":
        base = WatchIntentResponse.from_domain(result.watch_intent)
        return cls(
            **base.model_dump(),
            opportunity=(
                None
                if result.opportunity is None
                else IdentifiedOpportunityResponse.from_domain(result.opportunity)
            ),
        )


class WatchIntentListResponse(BaseModel):
    watch_intents: list[WatchIntentResponse]

    @classmethod
    def from_domain(cls, intents: list[WatchIntent]) -> "WatchIntentListResponse":
        return cls(
            watch_intents=[WatchIntentResponse.from_domain(i) for i in intents]
        )
