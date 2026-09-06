import logging
from typing import Self

from sqlalchemy import insert
from sqlalchemy.orm import Session

from backend.app.domain.events import WorkflowEvent
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import workflow_events_table


class SqlAlchemyEventStagingUnitOfWork:
    """Session lifecycle and transactional outbox shared by every SQLAlchemy unit of work.

    Staged events are persisted in the same transaction as the domain writes and only
    become `committed_events` once the commit succeeds, so a rollback publishes nothing.
    Subclasses add their own queries and set `_log_name`.
    """

    _logger = logging.getLogger(__name__)
    _log_name = "unit_of_work"

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._staged_events: list[WorkflowEvent] = []
        self._committed_events: tuple[WorkflowEvent, ...] = ()

    def __enter__(self) -> Self:
        self._session = self._session_factory.create_session()
        self._staged_events = []
        self._committed_events = ()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        session = self._require_session()
        try:
            if exc_type is None:
                self._persist_staged_events()
                session.commit()
                self._committed_events = tuple(self._staged_events)
                self._logger.info(
                    f"{self._log_name}.committed",
                    extra={
                        "workflow_id": (
                            self._committed_events[0].workflow_id if self._committed_events else "-"
                        ),
                        "event_count": len(self._committed_events),
                    },
                )
            else:
                session.rollback()
                self._committed_events = ()
                self._logger.warning(f"{self._log_name}.rolled_back")
        finally:
            self._staged_events = []
            session.close()
            self._session = None

    def stage_event(self, event: WorkflowEvent) -> None:
        self._staged_events.append(event)

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]:
        return self._committed_events

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError(f"{self._log_name} must be entered before use.")
        return self._session

    def _persist_staged_events(self) -> None:
        if not self._staged_events:
            return

        self._logger.info(
            f"{self._log_name}.persisting_events",
            extra={
                "workflow_id": self._staged_events[0].workflow_id,
                "event_count": len(self._staged_events),
            },
        )
        self._require_session().execute(
            insert(workflow_events_table),
            [
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "aggregate_id": event.aggregate_id,
                    "workflow_id": event.workflow_id,
                    "payload": event.payload.model_dump(mode="json"),
                    "occurred_at": event.occurred_at,
                }
                for event in self._staged_events
            ],
        )
