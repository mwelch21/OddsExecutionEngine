import logging

from backend.app.application.ports import WorkflowEventPublisher
from backend.app.domain.events import WorkflowEvent


class LoggingWorkflowEventPublisher(WorkflowEventPublisher):
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def publish(self, events: tuple[WorkflowEvent, ...]) -> None:
        self._logger.info(
            "workflow_events.publish_batch",
            extra={"event_count": len(events)},
        )
        for event in events:
            self._logger.info(
                "workflow_event.published",
                extra={
                    "event_id": event.id,
                    "event_type": event.event_type,
                    "aggregate_id": event.aggregate_id,
                    "workflow_id": event.workflow_id,
                    "payload": event.payload.model_dump(mode="json"),
                },
            )
