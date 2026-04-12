from backend.app.application.ports import WorkflowEventPublisher
from backend.app.domain.events import WorkflowEvent


class InMemoryWorkflowEventPublisher(WorkflowEventPublisher):
    def __init__(self) -> None:
        self.published_events: list[WorkflowEvent] = []

    def publish(self, events: tuple[WorkflowEvent, ...]) -> None:
        self.published_events.extend(events)
