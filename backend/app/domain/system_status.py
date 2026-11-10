"""Component status and operational metrics: what the Systems tab shows (#106).

Component status says whether one part of the system is reachable right now, read
straight from one signal the system already has. Operational metrics are facts
read from stored records, shown as they are. Neither is scored, combined into one
verdict, stored or emitted as an event (#92).
"""

from datetime import datetime
from enum import StrEnum

from backend.app.domain.base import DomainModel
from backend.app.domain.deliveries import DeliveryStatus
from backend.app.domain.quota import UpstreamCallOutcome
from backend.app.domain.refresh_records import RefreshScope


class ComponentName(StrEnum):
    """The components the API reports. The API itself is shown by the UI, from
    whether its own request got an answer."""

    DATABASE = "database"
    NOTIFIER = "notifier"
    PROVIDER = "provider"


class ComponentState(StrEnum):
    """Each component uses only the words its signal can prove (GLOSSARY.md)."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"


class ProviderAnswer(DomainModel):
    """How the newest upstream call ended, balance checks included (#121).

    `outcome` is None on a call recorded before outcomes were kept.
    """

    outcome: UpstreamCallOutcome | None
    observed_at: datetime


class SystemSignals(DomainModel):
    """The raw signals, read once per request.

    `notifier_listeners` counts open connections named `notifier-listener`; None
    when the count could not be read. `provider_answer` is None before any upstream call.
    """

    database_reachable: bool
    notifier_listeners: int | None
    provider_answer: ProviderAnswer | None
    observed_at: datetime


class ComponentStatus(DomainModel):
    component: ComponentName
    state: ComponentState
    observed_at: datetime


class LastSuccessfulRefresh(DomainModel):
    scope: RefreshScope
    sport_key: str
    event_id: str | None
    finished_at: datetime


class CreditsMetric(DomainModel):
    """The newest quota observation and the floor in force when it was read."""

    remaining: int | None
    used: int | None
    floor: int | None
    out_of_credits: bool
    below_floor: bool
    observed_at: datetime


class DeliveryCount(DomainModel):
    status: DeliveryStatus
    count: int


class PendingDeliveries(DomainModel):
    count: int
    oldest_created_at: datetime | None


class OperationalMetrics(DomainModel):
    """`credits` is None before any upstream call; delivery counts cover every
    status, zero included, for deliveries created since `deliveries_since`."""

    last_successful_refresh: LastSuccessfulRefresh | None
    credits: CreditsMetric | None
    deliveries_since: datetime
    delivery_counts: list[DeliveryCount]
    pending_deliveries: PendingDeliveries
