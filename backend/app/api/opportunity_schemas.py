from datetime import datetime

from pydantic import BaseModel

from backend.app.domain.models import MarketType, OpportunitySignal


class OpportunityResponse(BaseModel):
    id: str
    watch_intent_id: str
    event_id: str
    market_type: MarketType
    selection: str
    line: float | None
    matched_price: int
    target_price: int
    sportsbook: str
    created_at: datetime

    @classmethod
    def from_domain(cls, opportunity_signal: OpportunitySignal) -> "OpportunityResponse":
        return cls(
            id=opportunity_signal.id,
            watch_intent_id=opportunity_signal.watch_intent_id,
            event_id=opportunity_signal.event_id,
            market_type=opportunity_signal.market_type,
            selection=opportunity_signal.selection,
            line=opportunity_signal.line,
            matched_price=opportunity_signal.matched_price,
            target_price=opportunity_signal.target_price,
            sportsbook=opportunity_signal.sportsbook,
            created_at=opportunity_signal.created_at,
        )


class OpportunityListResponse(BaseModel):
    opportunities: list[OpportunityResponse]

    @classmethod
    def from_domain(
        cls,
        opportunity_signals: list[OpportunitySignal],
    ) -> "OpportunityListResponse":
        return cls(
            opportunities=[
                OpportunityResponse.from_domain(signal) for signal in opportunity_signals
            ]
        )
