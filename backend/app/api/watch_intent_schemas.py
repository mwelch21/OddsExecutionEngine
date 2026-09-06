from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from backend.app.api.market_validation import validate_market_fields
from backend.app.domain.models import MarketType, WatchIntent, WatchIntentDraft, WatchStatus


class WatchIntentCreateRequest(BaseModel):
    event_id: str = Field(min_length=1)
    market_type: MarketType
    selection: str = Field(min_length=1)
    line: float | None = None
    target_price: int
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def check_market_fields(self) -> "WatchIntentCreateRequest":
        validate_market_fields(self.market_type, self.selection, self.line)
        return self

    def to_domain(self) -> WatchIntentDraft:
        return WatchIntentDraft(
            event_id=self.event_id,
            market_type=self.market_type,
            selection=self.selection,
            target_price=self.target_price,
            line=self.line,
            expires_at=self.expires_at,
        )


class WatchIntentResponse(BaseModel):
    id: str
    event_id: str
    market_type: MarketType
    selection: str
    line: float | None
    target_price: int
    expires_at: datetime | None
    status: WatchStatus
    created_at: datetime

    @classmethod
    def from_domain(cls, watch_intent: WatchIntent) -> "WatchIntentResponse":
        return cls(
            id=watch_intent.id,
            event_id=watch_intent.event_id,
            market_type=watch_intent.market_type,
            selection=watch_intent.selection,
            line=watch_intent.line,
            target_price=watch_intent.target_price,
            expires_at=watch_intent.expires_at,
            status=watch_intent.status,
            created_at=watch_intent.created_at,
        )


class WatchIntentListResponse(BaseModel):
    watch_intents: list[WatchIntentResponse]

    @classmethod
    def from_domain(cls, watch_intents: list[WatchIntent]) -> "WatchIntentListResponse":
        return cls(
            watch_intents=[WatchIntentResponse.from_domain(watch) for watch in watch_intents]
        )
