from typing import Protocol, Self

from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import ExecutionRecommendation, OrderIntent, Quote


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
