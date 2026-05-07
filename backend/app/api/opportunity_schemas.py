from datetime import datetime

from pydantic import BaseModel

from backend.app.domain.models import MarketType, OpportunityWithValidity


class OpportunityResponse(BaseModel):
    id: str
    watch_intent_id: str
    event_id: str
    market_type: MarketType
    selection: str
    target_price: int
    line: float | None
    sportsbook: str
    matched_price: int
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
            sportsbook=opp.sportsbook,
            matched_price=opp.matched_price,
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
