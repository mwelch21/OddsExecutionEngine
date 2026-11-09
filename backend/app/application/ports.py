from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol, Self

from backend.app.domain.auto_refresh import AutoRefreshOutcome, AutoRefreshSettings
from backend.app.domain.base import DomainModel
from backend.app.domain.credits import BurnRow, RemainingReading
from backend.app.domain.deliveries import DeliveryFilter, DeliveryStatus, StoredDelivery
from backend.app.domain.destinations import Destination, DisabledReason, WebPushKeys
from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import (
    EventFilter,
    EventInfo,
    EventSport,
    EventSummary,
    ExecutionRecommendation,
    MarketQuotes,
    MarketType,
    Opportunity,
    OrderIntent,
    ProviderFetchReport,
    Quote,
    QuoteRefreshPersistenceResult,
    SupportedSport,
    WatchIntent,
    WatchStatus,
)
from backend.app.domain.public_events import OpportunityEventContext, PublicEvent
from backend.app.domain.quota import QuotaObservation, QuotaReading
from backend.app.domain.refresh_records import RefreshRecord, RefreshRecordFilter
from backend.app.domain.system_status import (
    LastSuccessfulRefresh,
    PendingDeliveries,
    ProviderAnswer,
)


class RecommendationUnitOfWork(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None: ...

    def create_order_intent(self, intent: OrderIntent) -> str: ...

    def list_quotes(self, event_id: str) -> list[Quote]: ...

    def create_execution_recommendation(
        self,
        order_intent_id: str,
        recommendation: ExecutionRecommendation,
    ) -> str: ...

    def stage_event(self, event: WorkflowEvent) -> None: ...

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]: ...


class RecommendationUnitOfWorkFactory(Protocol):
    def __call__(self) -> RecommendationUnitOfWork: ...


class WorkflowEventPublisher(Protocol):
    def publish(self, events: tuple[WorkflowEvent, ...]) -> None: ...


class QuoteIngestionProvider(Protocol):
    def list_quotes(
        self, event_id: str, sport: str
    ) -> tuple[list[Quote], ProviderFetchReport]: ...

    def list_quotes_for_sport(
        self, sport: str
    ) -> tuple[dict[str, list[Quote]], ProviderFetchReport]: ...

    def get_event_info(self, event_id: str) -> EventInfo | None: ...

    def list_supported_sports(self) -> list[SupportedSport]: ...

    def check_quota(self) -> None:
        """A free upstream balance check; its reading goes to the quota recorder."""
        ...


class QuotaRecorder(Protocol):
    """Receives the quota of every upstream call, served or refused (ADR-016).

    Returns the recorded observation's id, so the refresh that made the call can
    link to it; None when nothing was stored.
    """

    def record(self, reading: QuotaReading) -> int | None: ...


class QuotaUnitOfWork(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None: ...

    def lock(self) -> None:
        """Held until commit: one recorder at a time sees the previous observation."""
        ...

    def latest_observation(self) -> QuotaObservation | None: ...

    def add_observation(self, observation: QuotaObservation) -> int: ...

    def configured_floor(self) -> int | None: ...

    def stage_public_event(self, event: PublicEvent[DomainModel]) -> None: ...


class QuotaUnitOfWorkFactory(Protocol):
    def __call__(self) -> QuotaUnitOfWork: ...


class RefreshRecorder(Protocol):
    """Appends one refresh record in its own short transaction (#96).

    Called after ingestion settles, so a failed refresh is still recorded. A raise
    here is logged by the caller and never fails the refresh.
    """

    def record(self, record: RefreshRecord) -> None: ...


class QuoteIngestionUnitOfWork(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None: ...

    def persist_quotes(
        self,
        event_id: str,
        quotes: list[Quote],
        event_metadata: dict[str, object] | None = None,
    ) -> QuoteRefreshPersistenceResult: ...

    def get_event_sport(self, event_id: str) -> EventSport | None: ...

    def record_sport_refreshed(self, sport_key: str, refreshed_at: datetime) -> None: ...

    def stage_event(self, event: WorkflowEvent) -> None: ...

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]: ...


class QuoteIngestionUnitOfWorkFactory(Protocol):
    def __call__(self) -> QuoteIngestionUnitOfWork: ...


class AutoRefreshUnitOfWork(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None: ...

    def get_settings(self) -> AutoRefreshSettings: ...

    def save_settings(self, settings: AutoRefreshSettings) -> AutoRefreshSettings: ...

    def get_last_outcome(self) -> AutoRefreshOutcome | None:
        """The newest Auto-Refresh refresh record, in the status endpoint's shape."""
        ...

    def list_watched_event_sports(self, now: datetime) -> list[EventSport]: ...

    def get_sport_refresh_times(self) -> dict[str, datetime]: ...


class AutoRefreshUnitOfWorkFactory(Protocol):
    def __call__(self) -> AutoRefreshUnitOfWork: ...


class AutoRefreshCycleLock(Protocol):
    """At most one refresh cycle at a time, however many workers run.

    The context yields False when another holder has it; the caller skips the cycle.
    """

    def hold(self) -> AbstractContextManager[bool]: ...


class WatchIntentUnitOfWork(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None: ...

    def create_watch_intent(
        self,
        event_id: str,
        market_type: MarketType,
        selection: str,
        target_price: int,
        line: float | None,
        expires_at: datetime | None = None,
    ) -> WatchIntent: ...

    def cancel_watch_intent(self, watch_intent_id: str) -> WatchIntent: ...

    def trigger_watch_intents(self, watch_intent_ids: list[str]) -> list[WatchIntent]: ...

    def expire_watch_intents(self, watch_intent_ids: list[str]) -> list[WatchIntent]: ...

    def get_watch_intent(self, watch_intent_id: str) -> WatchIntent | None: ...

    def list_watch_intents(
        self,
        event_id: str | None = None,
        status: WatchStatus | None = None,
    ) -> list[WatchIntent]: ...

    def list_active_watch_intents(
        self, event_id: str | None = None
    ) -> list[WatchIntent]: ...

    def list_quotes(self, event_id: str) -> list[Quote]: ...

    def get_market_id_lookup(
        self, event_id: str
    ) -> dict[tuple[str, str, str, float | None], str]: ...

    def create_opportunities(
        self, opportunities: list[Opportunity]
    ) -> list[Opportunity]: ...

    def list_opportunities(
        self, event_id: str | None = None
    ) -> list[Opportunity]: ...

    def get_opportunity(self, opportunity_id: str) -> Opportunity | None: ...

    def get_latest_quote_times(
        self, opportunities: list[Opportunity]
    ) -> list[tuple[Opportunity, datetime | None]]: ...

    def get_event_starts_at(self, event_external_id: str) -> datetime | None: ...

    def get_opportunity_event_context(
        self, opportunity: Opportunity
    ) -> OpportunityEventContext: ...

    def stage_event(self, event: WorkflowEvent) -> None: ...

    def stage_public_event(self, event: PublicEvent[DomainModel]) -> None: ...

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]: ...


class WatchIntentUnitOfWorkFactory(Protocol):
    def __call__(self) -> WatchIntentUnitOfWork: ...


class EventReadUnitOfWork(Protocol):
    """Read-only access to stored events. Browsing never writes."""

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None: ...

    def count_events(self, event_filter: EventFilter, now: datetime) -> int: ...

    def list_events(
        self,
        event_filter: EventFilter,
        now: datetime,
        limit: int,
        offset: int,
    ) -> list[EventSummary]: ...

    def get_event(self, event_id: str) -> EventSummary | None: ...

    def list_market_quotes(self, event_id: str) -> list[MarketQuotes]: ...


class EventReadUnitOfWorkFactory(Protocol):
    def __call__(self) -> EventReadUnitOfWork: ...


class DeliveryReadUnitOfWork(Protocol):
    """Read-only access to the delivery log. The notifier is the only writer."""

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None: ...

    def count_deliveries(self, delivery_filter: DeliveryFilter) -> int: ...

    def list_deliveries(
        self, delivery_filter: DeliveryFilter, limit: int, offset: int
    ) -> list[StoredDelivery]: ...


class DeliveryReadUnitOfWorkFactory(Protocol):
    def __call__(self) -> DeliveryReadUnitOfWork: ...


class SystemStatusReadUnitOfWork(Protocol):
    """Reads behind component status and operational metrics (#106). DB-only: the
    provider's state comes from stored refreshes, never a live probe."""

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None: ...

    def database_reachable(self) -> bool:
        """`SELECT 1` answered. False, never an error, when it did not."""
        ...

    def notifier_listener_count(self) -> int | None:
        """Open `notifier-listener` connections; None when that cannot be read."""
        ...

    def newest_provider_answer(self) -> ProviderAnswer | None: ...

    def last_successful_refresh(self) -> LastSuccessfulRefresh | None: ...

    def latest_quota_observation(self) -> QuotaObservation | None: ...

    def configured_quota_floor(self) -> int | None: ...

    def delivery_counts_since(self, since: datetime) -> dict[DeliveryStatus, int]: ...

    def pending_deliveries(self) -> PendingDeliveries: ...


class SystemStatusReadUnitOfWorkFactory(Protocol):
    def __call__(self) -> SystemStatusReadUnitOfWork: ...


class DestinationUnitOfWork(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None: ...

    def get_web_push_destination(self, address: str) -> Destination | None: ...

    def create_web_push_destination(
        self, address: str, keys: WebPushKeys, label: str
    ) -> Destination: ...

    def refresh_web_push_destination(
        self, destination_id: str, keys: WebPushKeys, reactivate: bool
    ) -> Destination: ...

    def list_destinations(self) -> list[Destination]: ...

    def get_destination(self, destination_id: str) -> Destination | None: ...

    def update_destination(
        self, destination_id: str, label: str | None, reactivate: bool
    ) -> Destination:
        """Reactivation never applies to a `gone` row; the result shows whether it did."""
        ...

    def disable_destination(
        self, destination_id: str, reason: DisabledReason
    ) -> Destination: ...

    def latest_test_requested_at(self, destination_id: str) -> datetime | None: ...

    def add_public_event(self, event: PublicEvent[DomainModel]) -> None: ...


class DestinationUnitOfWorkFactory(Protocol):
    def __call__(self) -> DestinationUnitOfWork: ...


class AdminReadUnitOfWork(Protocol):
    """Read-only access for the Admin view. Nothing here writes or calls upstream."""

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None: ...

    def count_refreshes(self, refresh_filter: RefreshRecordFilter) -> int: ...

    def list_refreshes(
        self, refresh_filter: RefreshRecordFilter, limit: int, offset: int
    ) -> list[RefreshRecord]: ...


class AdminReadUnitOfWorkFactory(Protocol):
    def __call__(self) -> AdminReadUnitOfWork: ...


class CreditReadUnitOfWork(Protocol):
    """Read-only access to quota observations for the Credits tab (#104)."""

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None: ...

    def list_remaining(self, since: datetime) -> list[RemainingReading]:
        """Observations from `since` on that know the balance, in observation order."""
        ...

    def sum_burn(self, starts_at: datetime, ends_at: datetime) -> list[BurnRow]:
        """Calls and credits per (sport, kind) observed in [starts_at, ends_at)."""
        ...


class CreditReadUnitOfWorkFactory(Protocol):
    def __call__(self) -> CreditReadUnitOfWork: ...
