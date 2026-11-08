"""Deliveries as the operator reads them: the delivery log (#105).

A delivery is one public event going to one destination (ADR-015). Only the Go
notifier writes deliveries; the API reads them. The log carries a short subject
built from the event and the destination's label and channel, never the push
address, its keys or the raw event payload.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from backend.app.domain.base import DomainModel
from backend.app.domain.destinations import Channel


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    EXPIRED = "expired"
    GONE = "gone"


class DeliveryFilter(DomainModel):
    """Each filter narrows independently; unset means "any"."""

    status: DeliveryStatus | None = None
    event_type: str | None = None
    destination_id: str | None = None


class StoredDelivery(DomainModel):
    """One delivery row joined to its event and destination.

    `event_data` is the event's `data`, read only to build the subject line. It
    never leaves the application layer.
    """

    id: str
    event_id: str
    event_type: str
    event_data: dict[str, Any]
    destination_id: str
    destination_label: str
    channel: Channel
    status: DeliveryStatus
    attempts: int
    last_error: str | None
    created_at: datetime
    ended_at: datetime | None


class DeliveryLogEntry(DomainModel):
    """A delivery as the log shows it. `last_error` is an allowlisted summary,
    never the stored text."""

    id: str
    event_id: str
    event_type: str
    subject: str
    destination_id: str
    destination_label: str
    channel: Channel
    status: DeliveryStatus
    attempts: int
    last_error: str | None
    created_at: datetime
    ended_at: datetime | None


class DeliveryPage(DomainModel):
    """A page of the delivery log plus everything needed to render "page 2 of 7"."""

    deliveries: list[DeliveryLogEntry]
    page: int
    page_size: int
    total_items: int

    @property
    def total_pages(self) -> int:
        return -(-self.total_items // self.page_size) if self.page_size > 0 else 0
