from datetime import datetime

from pydantic import BaseModel

from backend.app.domain.deliveries import DeliveryStatus
from backend.app.domain.refresh_records import RefreshScope
from backend.app.domain.system_status import OperationalMetrics


class LastSuccessfulRefreshResponse(BaseModel):
    """`event_id` is null for a sport-wide refresh."""

    scope: RefreshScope
    sport: str
    event_id: str | None
    finished_at: datetime


class CreditsResponse(BaseModel):
    """The newest quota observation. `below_floor` drives the attention pill."""

    remaining: int | None
    used: int | None
    floor: int | None
    out_of_credits: bool
    below_floor: bool
    observed_at: datetime


class DeliveryCountResponse(BaseModel):
    status: DeliveryStatus
    count: int


class PendingDeliveriesResponse(BaseModel):
    count: int
    oldest_created_at: datetime | None


class MetricsResponse(BaseModel):
    """Facts from stored records, shown as they are. `credits` is null before any
    upstream call; delivery counts cover deliveries created since `deliveries_since`."""

    last_successful_refresh: LastSuccessfulRefreshResponse | None
    credits: CreditsResponse | None
    deliveries_since: datetime
    delivery_counts: list[DeliveryCountResponse]
    pending_deliveries: PendingDeliveriesResponse

    @classmethod
    def from_domain(cls, metrics: OperationalMetrics) -> "MetricsResponse":
        refresh = metrics.last_successful_refresh
        credits = metrics.credits
        return cls(
            last_successful_refresh=None
            if refresh is None
            else LastSuccessfulRefreshResponse(
                scope=refresh.scope,
                sport=refresh.sport_key,
                event_id=refresh.event_id,
                finished_at=refresh.finished_at,
            ),
            credits=None
            if credits is None
            else CreditsResponse(
                remaining=credits.remaining,
                used=credits.used,
                floor=credits.floor,
                out_of_credits=credits.out_of_credits,
                below_floor=credits.below_floor,
                observed_at=credits.observed_at,
            ),
            deliveries_since=metrics.deliveries_since,
            delivery_counts=[
                DeliveryCountResponse(status=c.status, count=c.count)
                for c in metrics.delivery_counts
            ],
            pending_deliveries=PendingDeliveriesResponse(
                count=metrics.pending_deliveries.count,
                oldest_created_at=metrics.pending_deliveries.oldest_created_at,
            ),
        )
