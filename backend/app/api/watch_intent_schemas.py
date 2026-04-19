from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from backend.app.domain.models import MarketType, WatchIntent


class CreateWatchIntentRequest(BaseModel):
    event_id: str = Field(min_length=1)
    market_type: MarketType
    selection: str = Field(min_length=1)
    line: float | None = None
    target_price: int

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
    status: str
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
            status=intent.status,
            created_at=intent.created_at,
        )


class WatchIntentListResponse(BaseModel):
    watch_intents: list[WatchIntentResponse]

    @classmethod
    def from_domain(cls, intents: list[WatchIntent]) -> "WatchIntentListResponse":
        return cls(
            watch_intents=[WatchIntentResponse.from_domain(i) for i in intents]
        )
