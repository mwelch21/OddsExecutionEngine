from datetime import datetime

from pydantic import BaseModel

from backend.app.domain.models import MarketType, OpportunityWithValidity


class MatchingQuoteResponse(BaseModel):
    sportsbook: str
    price: int


class OpportunityResponse(BaseModel):
    """The books that were fillable at detection, plus whether that still holds.

    `matching_quotes` is returned as stored rather than re-checked, so the reader can
    tell "here is what we found" from "here is what is true now". `is_valid` /
    `invalid_reason` carry the latter, judged against the best book alone.
    """

    id: str
    watch_intent_id: str
    event_id: str
    market_type: MarketType
    selection: str
    target_price: int
    line: float | None
    best_sportsbook: str
    best_price: int
    matching_quotes: list[MatchingQuoteResponse]
    created_at: datetime | None
    is_valid: bool
    invalid_reason: str | None

    @classmethod
    def from_domain(cls, owv: OpportunityWithValidity) -> "OpportunityResponse":
        opp = owv.opportunity
        return cls(
            id=opp.id,
            watch_intent_id=opp.watch_intent_id,
            event_id=opp.event_id,
            market_type=opp.market_type,
            selection=opp.selection,
            target_price=opp.target_price,
            line=opp.line,
            best_sportsbook=opp.best_sportsbook,
            best_price=opp.best_price,
            matching_quotes=[
                MatchingQuoteResponse(sportsbook=quote.sportsbook, price=quote.price)
                for quote in opp.matching_quotes
            ],
            created_at=opp.created_at,
            is_valid=owv.is_valid,
            invalid_reason=owv.reason,
        )


class OpportunityListResponse(BaseModel):
    opportunities: list[OpportunityResponse]

    @classmethod
    def from_domain(
        cls, items: list[OpportunityWithValidity]
    ) -> "OpportunityListResponse":
        return cls(
            opportunities=[OpportunityResponse.from_domain(i) for i in items]
        )
