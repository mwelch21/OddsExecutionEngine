from datetime import datetime

from pydantic import BaseModel

from backend.app.domain.deliveries import DeliveryLogEntry, DeliveryPage, DeliveryStatus
from backend.app.domain.destinations import Channel


class DeliveryResponse(BaseModel):
    """One delivery in the log. The destination shows as its label and channel
    only, and the event as a short subject: never the push address, its keys or
    the raw event payload. `ended_at` is null while the delivery is pending."""

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

    @classmethod
    def from_domain(cls, entry: DeliveryLogEntry) -> "DeliveryResponse":
        return cls(
            id=entry.id,
            event_id=entry.event_id,
            event_type=entry.event_type,
            subject=entry.subject,
            destination_id=entry.destination_id,
            destination_label=entry.destination_label,
            channel=entry.channel,
            status=entry.status,
            attempts=entry.attempts,
            last_error=entry.last_error,
            created_at=entry.created_at,
            ended_at=entry.ended_at,
        )


class DeliveryListResponse(BaseModel):
    deliveries: list[DeliveryResponse]
    page: int
    page_size: int
    total_items: int
    total_pages: int

    @classmethod
    def from_domain(cls, page: DeliveryPage) -> "DeliveryListResponse":
        return cls(
            deliveries=[DeliveryResponse.from_domain(entry) for entry in page.deliveries],
            page=page.page,
            page_size=page.page_size,
            total_items=page.total_items,
            total_pages=page.total_pages,
        )
