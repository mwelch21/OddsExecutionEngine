import logging
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from backend.app.application.ports import (
    WatchEvaluationUnitOfWorkFactory,
    WorkflowEventPublisher,
)
from backend.app.application.timing import elapsed_ms
from backend.app.domain.events import (
    build_target_price_became_fillable_event,
    build_watch_intent_expired_event,
)
from backend.app.domain.models import (
    OpportunitySignal,
    TriggeredWatch,
    WatchEvaluationSummary,
    WatchStatus,
)
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine


class WatchEvaluationService:
    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        unit_of_work_factory: WatchEvaluationUnitOfWorkFactory,
        watch_evaluation_engine: WatchEvaluationEngine,
        workflow_event_publisher: WorkflowEventPublisher,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._watch_evaluation_engine = watch_evaluation_engine
        self._workflow_event_publisher = workflow_event_publisher

    def evaluate_event(self, event_id: str) -> WatchEvaluationSummary:
        started_at = perf_counter()
        evaluation_id = str(uuid4())

        self._logger.info(
            "watch_evaluation.started",
            extra={"workflow_id": evaluation_id, "event_id": event_id},
        )

        try:
            with self._unit_of_work_factory() as unit_of_work:
                active_watches = unit_of_work.list_active_watch_intents(event_id)
                quotes = unit_of_work.list_quotes(event_id)
                result = self._watch_evaluation_engine.evaluate(
                    active_watches,
                    quotes,
                    now=datetime.now(UTC),
                )

                for expired_watch in result.expired:
                    unit_of_work.update_watch_intent_status(
                        expired_watch.id,
                        WatchStatus.EXPIRED,
                    )
                    unit_of_work.stage_event(build_watch_intent_expired_event(expired_watch))

                for triggered_watch in result.triggered:
                    opportunity_signal = _build_opportunity_signal(triggered_watch)
                    unit_of_work.create_opportunity_signal(opportunity_signal)
                    unit_of_work.update_watch_intent_status(
                        triggered_watch.watch_intent.id,
                        WatchStatus.TRIGGERED,
                    )
                    unit_of_work.stage_event(
                        build_target_price_became_fillable_event(opportunity_signal)
                    )

            self._workflow_event_publisher.publish(unit_of_work.committed_events)
        except Exception:
            self._logger.exception(
                "watch_evaluation.failed",
                extra={
                    "workflow_id": evaluation_id,
                    "event_id": event_id,
                    "duration_ms": elapsed_ms(started_at),
                },
            )
            raise

        summary = WatchEvaluationSummary(
            event_id=event_id,
            evaluated_watch_count=len(active_watches),
            triggered_watch_count=len(result.triggered),
            expired_watch_count=len(result.expired),
            emitted_event_types=[event.event_type for event in unit_of_work.committed_events],
        )

        self._logger.info(
            "watch_evaluation.completed",
            extra={
                "workflow_id": evaluation_id,
                "event_id": event_id,
                "event_count": len(summary.emitted_event_types),
                "duration_ms": elapsed_ms(started_at),
            },
        )
        return summary

    def list_opportunities(self, *, event_id: str | None = None) -> list[OpportunitySignal]:
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.list_opportunity_signals(event_id=event_id)

    def get_opportunity(self, opportunity_signal_id: str) -> OpportunitySignal | None:
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.get_opportunity_signal(opportunity_signal_id)


def _build_opportunity_signal(triggered_watch: TriggeredWatch) -> OpportunitySignal:
    watch_intent = triggered_watch.watch_intent
    quote = triggered_watch.quote

    return OpportunitySignal(
        id=str(uuid4()),
        watch_intent_id=watch_intent.id,
        event_id=watch_intent.event_id,
        market_type=watch_intent.market_type,
        selection=watch_intent.selection,
        line=watch_intent.line,
        matched_price=quote.price,
        target_price=watch_intent.target_price,
        sportsbook=quote.sportsbook,
        created_at=datetime.now(UTC),
    )
