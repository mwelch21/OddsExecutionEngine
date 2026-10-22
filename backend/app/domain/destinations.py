"""Destinations: the addresses public events are delivered to (ADR-015).

A destination is one address on one channel: today a browser's Web Push
subscription, later a webhook URL. It is active until it is disabled, either by
the operator (`user_removed`) or because the channel rejected it (`gone`).
"""

from datetime import datetime
from enum import StrEnum

from backend.app.domain.base import DomainModel


class Channel(StrEnum):
    WEB_PUSH = "web_push"


class DisabledReason(StrEnum):
    USER_REMOVED = "user_removed"
    GONE = "gone"


class WebPushKeys(DomainModel):
    """The browser's encryption keys. `auth` is a secret and never leaves the API."""

    p256dh: str
    auth: str


class Destination(DomainModel):
    id: str
    channel: Channel
    label: str
    address: str
    created_at: datetime | None = None
    last_delivered_at: datetime | None = None
    disabled_at: datetime | None = None
    disabled_reason: DisabledReason | None = None

    @property
    def is_active(self) -> bool:
        return self.disabled_at is None
