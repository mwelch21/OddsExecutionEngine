from datetime import datetime
from typing import Protocol, Self

from backend.app.domain.base import DomainModel
from backend.app.domain.destinations import Destination, WebPushKeys
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
    def list_quotes(self, event_id: str, sport: str) -> list[Quote]: ...

    def list_quotes_for_sport(
        self, sport: str
    ) -> tuple[dict[str, list[Quote]], ProviderFetchReport]: ...

    def get_event_info(self, event_id: str) -> EventInfo | None: ...

    def list_supported_sports(self) -> list[SupportedSport]: ...


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

    def stage_event(self, event: WorkflowEvent) -> None: ...

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]: ...


class QuoteIngestionUnitOfWorkFactory(Protocol):
    def __call__(self) -> QuoteIngestionUnitOfWork: ...


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


class DestinationUnitOfWorkFactory(Protocol):
    def __call__(self) -> DestinationUnitOfWork: ...
