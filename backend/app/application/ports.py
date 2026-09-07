from datetime import datetime
from typing import Protocol, Self

from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import (
    EventInfo,
    ExecutionRecommendation,
    MarketType,
    Opportunity,
    OrderIntent,
    Quote,
    QuoteRefreshPersistenceResult,
    WatchIntent,
    WatchStatus,
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
    def list_quotes(self, event_id: str) -> list[Quote]: ...

    def list_quotes_for_sport(self, sport: str) -> dict[str, list[Quote]]: ...

    def get_event_info(self, event_id: str) -> EventInfo | None: ...


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

    def stage_event(self, event: WorkflowEvent) -> None: ...

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]: ...


class WatchIntentUnitOfWorkFactory(Protocol):
    def __call__(self) -> WatchIntentUnitOfWork: ...
