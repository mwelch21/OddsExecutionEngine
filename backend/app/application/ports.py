from typing import Protocol, Self

from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import (
    ExecutionRecommendation,
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

    def create_watch_intent(self, watch_intent: WatchIntent) -> None: ...

    def list_watch_intents(
        self,
        *,
        event_id: str | None = None,
        status: WatchStatus | None = None,
    ) -> list[WatchIntent]: ...

    def get_watch_intent(self, watch_intent_id: str) -> WatchIntent | None: ...

    def update_watch_intent_status(self, watch_intent_id: str, status: WatchStatus) -> None: ...

    def stage_event(self, event: WorkflowEvent) -> None: ...

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]: ...


class WatchIntentUnitOfWorkFactory(Protocol):
    def __call__(self) -> WatchIntentUnitOfWork: ...
