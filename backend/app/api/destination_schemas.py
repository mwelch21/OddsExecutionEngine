from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from backend.app.domain.destinations import Channel, Destination, DisabledReason


class VapidPublicKeyResponse(BaseModel):
    public_key: str


class WebPushSubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)


class RegisterWebPushRequest(BaseModel):
    """The browser's `PushSubscription.toJSON()`, plus an optional label."""

    endpoint: str = Field(min_length=1, pattern=r"^https://")
    keys: WebPushSubscriptionKeys
    label: str = Field(default="Browser", min_length=1, max_length=128)


class UpdateDestinationRequest(BaseModel):
    """Rename, re-enable, or both. Removing is `DELETE`, so `active` only takes `true`."""

    label: str | None = Field(default=None, min_length=1, max_length=128)
    active: Literal[True] | None = None

    @model_validator(mode="after")
    def _requires_a_change(self) -> Self:
        if self.label is None and self.active is None:
            raise ValueError("Give a label, active: true, or both.")
        return self


class DestinationResponse(BaseModel):
    """Safe fields and status only. Channel secrets are never returned."""

    id: str
    channel: Channel
    label: str
    address: str
    active: bool
    created_at: datetime | None
    last_delivered_at: datetime | None
    disabled_at: datetime | None
    disabled_reason: DisabledReason | None

    @classmethod
    def from_domain(cls, destination: Destination) -> "DestinationResponse":
        return cls(
            id=destination.id,
            channel=destination.channel,
            label=destination.label,
            address=destination.address,
            active=destination.is_active,
            created_at=destination.created_at,
            last_delivered_at=destination.last_delivered_at,
            disabled_at=destination.disabled_at,
            disabled_reason=destination.disabled_reason,
        )


class DestinationListResponse(BaseModel):
    destinations: list[DestinationResponse]


class SendTestResponse(BaseModel):
    """The test was queued. Delivery happens asynchronously via the notifier."""

    public_event_id: str
    destination_id: str
