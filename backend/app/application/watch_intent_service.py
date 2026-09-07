import logging
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from backend.app.application.ports import (
    WatchIntentUnitOfWorkFactory,
    WorkflowEventPublisher,
)
from backend.app.application.timing import elapsed_ms
from backend.app.domain.events import (
    build_watch_intent_cancelled_event,
    build_watch_intent_submitted_event,
)
from backend.app.domain.models import WatchIntent, WatchIntentDraft, WatchStatus


class WatchIntentService:
    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        unit_of_work_factory: WatchIntentUnitOfWorkFactory,
        workflow_event_publisher: WorkflowEventPublisher,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._workflow_event_publisher = workflow_event_publisher

    def create_watch(self, draft: WatchIntentDraft) -> WatchIntent:
        started_at = perf_counter()
        watch_intent = WatchIntent(
            id=str(uuid4()),
            event_id=draft.event_id,
            market_type=draft.market_type,
            selection=draft.selection,
            target_price=draft.target_price,
            line=draft.line,
            expires_at=draft.expires_at,
            status=WatchStatus.ACTIVE,
            created_at=datetime.now(UTC),
        )

        self._logger.info(
            "watch_intent.create.started",
            extra={
                "path": "/watch-intents",
                "workflow_id": watch_intent.id,
                "event_id": watch_intent.event_id,
            },
        )

        try:
            with self._unit_of_work_factory() as unit_of_work:
                unit_of_work.create_watch_intent(watch_intent)
                unit_of_work.stage_event(build_watch_intent_submitted_event(watch_intent))

            self._workflow_event_publisher.publish(unit_of_work.committed_events)
        except Exception:
            self._logger.exception(
                "watch_intent.create.failed",
                extra={
                    "workflow_id": watch_intent.id,
                    "duration_ms": elapsed_ms(started_at),
                },
            )
            raise

        self._logger.info(
            "watch_intent.create.completed",
            extra={
                "workflow_id": watch_intent.id,
                "event_count": len(unit_of_work.committed_events),
                "duration_ms": elapsed_ms(started_at),
            },
        )
        return watch_intent

    def list_watches(
        self,
        *,
        event_id: str | None = None,
        status: WatchStatus | None = None,
    ) -> list[WatchIntent]:
        now = datetime.now(UTC)

        with self._unit_of_work_factory() as unit_of_work:
            stored = unit_of_work.list_watch_intents(
                event_id=event_id,
                status=status,
            )
            if status is WatchStatus.EXPIRED:
                # A watch whose TTL passed with no refresh is still stored as active.
                stored = stored + unit_of_work.list_watch_intents(
                    event_id=event_id,
                    status=WatchStatus.ACTIVE,
                )

        projected = [watch.with_effective_status(now) for watch in stored]
        if status is not None:
            projected = [watch for watch in projected if watch.status is status]

        return sorted(projected, key=lambda watch: watch.created_at)

    def get_watch(self, watch_intent_id: str) -> WatchIntent | None:
        now = datetime.now(UTC)

        with self._unit_of_work_factory() as unit_of_work:
            watch_intent = unit_of_work.get_watch_intent(watch_intent_id)

        return None if watch_intent is None else watch_intent.with_effective_status(now)

    def cancel_watch(self, watch_intent_id: str) -> WatchIntent | None:
        started_at = perf_counter()

        self._logger.info(
            "watch_intent.cancel.started",
            extra={
                "path": "/watch-intents/{watch_intent_id}",
                "workflow_id": watch_intent_id,
            },
        )

        try:
            with self._unit_of_work_factory() as unit_of_work:
                watch_intent = unit_of_work.get_watch_intent(watch_intent_id)
                if watch_intent is None:
                    return None

                if watch_intent.status is WatchStatus.CANCELLED:
                    return watch_intent

                cancelled = watch_intent.model_copy(update={"status": WatchStatus.CANCELLED})
                unit_of_work.update_watch_intent_status(watch_intent_id, WatchStatus.CANCELLED)
                unit_of_work.stage_event(build_watch_intent_cancelled_event(cancelled))

            self._workflow_event_publisher.publish(unit_of_work.committed_events)
        except Exception:
            self._logger.exception(
                "watch_intent.cancel.failed",
                extra={
                    "workflow_id": watch_intent_id,
                    "duration_ms": elapsed_ms(started_at),
                },
            )
            raise

        self._logger.info(
            "watch_intent.cancel.completed",
            extra={
                "workflow_id": watch_intent_id,
                "event_count": len(unit_of_work.committed_events),
                "duration_ms": elapsed_ms(started_at),
            },
        )
        return cancelled
