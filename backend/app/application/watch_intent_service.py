import logging
from datetime import UTC, datetime
from time import perf_counter

from backend.app.application.ports import (
    WatchIntentUnitOfWork,
    WatchIntentUnitOfWorkFactory,
    WorkflowEventPublisher,
)
from backend.app.domain.events import (
    build_opportunity_identified_event,
    build_watch_intent_cancelled_event,
    build_watch_intent_created_event,
    build_watch_intent_expired_event,
    build_watch_intent_triggered_event,
)
from backend.app.domain.models import (
    MarketType,
    Opportunity,
    OpportunityWithValidity,
    WatchIntent,
    WatchIntentCreationResult,
    WatchStatus,
)
from backend.app.engines.opportunity_validity_engine import OpportunityValidityEngine
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine


class WatchIntentAlreadyTriggeredError(Exception):
    """Raised when a cancel would overwrite a watch's terminal `triggered` status."""

    def __init__(self, watch_intent_id: str) -> None:
        super().__init__(f"Watch intent {watch_intent_id} has already been triggered.")
        self.watch_intent_id = watch_intent_id


class WatchIntentService:
    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        unit_of_work_factory: WatchIntentUnitOfWorkFactory,
        workflow_event_publisher: WorkflowEventPublisher,
        watch_evaluation_engine: WatchEvaluationEngine,
        opportunity_validity_engine: OpportunityValidityEngine,
        opportunity_ttl_minutes: int,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._workflow_event_publisher = workflow_event_publisher
        self._watch_evaluation_engine = watch_evaluation_engine
        self._opportunity_validity_engine = opportunity_validity_engine
        self._opportunity_ttl_minutes = opportunity_ttl_minutes

    def create_watch_intent(
        self,
        event_id: str,
        market_type: MarketType,
        selection: str,
        target_price: int,
        line: float | None = None,
        expires_at: datetime | None = None,
    ) -> WatchIntentCreationResult:
        started_at = perf_counter()
        inserted_opportunities: list[Opportunity] = []

        self._logger.info(
            "watch_intent.create.started",
            extra={
                "path": "/watch-intents",
                "event_id": event_id,
                "market_type": market_type.value,
                "selection": selection,
            },
        )

        try:
            with self._unit_of_work_factory() as uow:
                intent = uow.create_watch_intent(
                    event_id=event_id,
                    market_type=market_type,
                    selection=selection,
                    target_price=target_price,
                    line=line,
                    expires_at=expires_at,
                )

                uow.stage_event(
                    build_watch_intent_created_event(
                        watch_intent_id=intent.id,
                        intent=intent,
                    )
                )

                # Immediate evaluation against current quotes. A watch created with a
                # TTL already in the past can never fill, so it is not evaluated.
                new_opportunities: list[Opportunity] = []
                if not intent.is_expired_at(datetime.now(UTC)):
                    quotes = uow.list_quotes(event_id)
                    market_id_lookup = uow.get_market_id_lookup(event_id)
                    new_opportunities = self._watch_evaluation_engine.evaluate(
                        watch_intents=[intent],
                        quotes=quotes,
                        market_id_lookup=market_id_lookup,
                    )

                if new_opportunities:
                    inserted_opportunities = uow.create_opportunities(new_opportunities)
                    retired = self._notify_and_retire(uow, inserted_opportunities)
                    # The response reports the watch as the caller will next read it.
                    intent = next(
                        (r for r in retired if r.id == intent.id),
                        intent,
                    )

            self._workflow_event_publisher.publish(uow.committed_events)
        except Exception:
            self._logger.exception(
                "watch_intent.create.failed",
                extra={
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise

        self._logger.info(
            "watch_intent.create.completed",
            extra={
                "watch_intent_id": intent.id,
                "opportunity_count": len(inserted_opportunities),
                "event_count": len(uow.committed_events),
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return WatchIntentCreationResult(
            watch_intent=intent,
            opportunity=inserted_opportunities[0] if inserted_opportunities else None,
        )

    def cancel_watch_intent(self, watch_intent_id: str) -> WatchIntent:
        started_at = perf_counter()

        self._logger.info(
            "watch_intent.cancel.started",
            extra={"watch_intent_id": watch_intent_id},
        )

        try:
            with self._unit_of_work_factory() as uow:
                # `triggered` is terminal. Letting a cancel overwrite it would make
                # "which of my watches fired?" unanswerable from watch state.
                existing = uow.get_watch_intent(watch_intent_id)
                if existing is not None and existing.status is WatchStatus.TRIGGERED:
                    raise WatchIntentAlreadyTriggeredError(watch_intent_id)

                intent = uow.cancel_watch_intent(watch_intent_id)
                uow.stage_event(
                    build_watch_intent_cancelled_event(
                        watch_intent_id=watch_intent_id,
                        intent=intent,
                    )
                )

            self._workflow_event_publisher.publish(uow.committed_events)
        except Exception:
            self._logger.exception(
                "watch_intent.cancel.failed",
                extra={
                    "watch_intent_id": watch_intent_id,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise

        self._logger.info(
            "watch_intent.cancel.completed",
            extra={
                "watch_intent_id": watch_intent_id,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return intent

    def get_watch_intent(self, watch_intent_id: str) -> WatchIntent | None:
        now = datetime.now(UTC)
        with self._unit_of_work_factory() as uow:
            intent = uow.get_watch_intent(watch_intent_id)

        return None if intent is None else intent.with_effective_status(now)

    def list_watch_intents(
        self,
        event_id: str | None = None,
        status: WatchStatus | None = None,
    ) -> list[WatchIntent]:
        """List watches, defaulting to those that can still produce an opportunity.

        Without a status filter this means stored-active, TTL not passed, and on an
        event that has not started.
        """
        now = datetime.now(UTC)

        with self._unit_of_work_factory() as uow:
            stored = uow.list_watch_intents(event_id=event_id, status=status)
            if status is WatchStatus.EXPIRED:
                # A watch whose TTL passed before the next evaluation is stored active,
                # so scanning only stored-expired rows would hide it from both filters.
                stored = stored + uow.list_watch_intents(
                    event_id=event_id,
                    status=WatchStatus.ACTIVE,
                )

            wanted = status if status is not None else WatchStatus.ACTIVE
            intents = [
                projected
                for projected in (intent.with_effective_status(now) for intent in stored)
                if projected.status is wanted
            ]

            if wanted is not WatchStatus.ACTIVE or not intents:
                return _sorted_by_creation(intents, now)

            starts_at_map = {
                event: uow.get_event_starts_at(event)
                for event in {intent.event_id for intent in intents}
            }

        return _sorted_by_creation(
            [
                intent
                for intent in intents
                if not _event_has_started(starts_at_map.get(intent.event_id), now)
            ],
            now,
        )

    def list_opportunities(
        self, event_id: str | None = None
    ) -> list[OpportunityWithValidity]:
        now = datetime.now(UTC)
        with self._unit_of_work_factory() as uow:
            opportunities = uow.list_opportunities(event_id)
            if not opportunities:
                return []
            items = uow.get_latest_quote_times(opportunities)

        return self._opportunity_validity_engine.check_validity_batch(
            items=items,
            ttl_minutes=self._opportunity_ttl_minutes,
            now=now,
        )

    def get_opportunity(self, opportunity_id: str) -> OpportunityWithValidity | None:
        now = datetime.now(UTC)
        with self._unit_of_work_factory() as uow:
            opportunity = uow.get_opportunity(opportunity_id)
            if opportunity is None:
                return None
            items = uow.get_latest_quote_times([opportunity])

        return self._opportunity_validity_engine.check_validity_batch(
            items=items,
            ttl_minutes=self._opportunity_ttl_minutes,
            now=now,
        )[0]

    def _notify_and_retire(
        self,
        uow: WatchIntentUnitOfWork,
        opportunities: list[Opportunity],
    ) -> list[WatchIntent]:
        """Notify once per opportunity and retire the watch that produced it.

        Only opportunities the DB actually accepted reach here, and the transition
        commits in the same transaction as the insert. A row therefore cannot exist
        without its watch being `triggered`, so a concurrent evaluation that loses
        the insert race leaves the watch correctly retired by the winner.

        `OpportunityIdentified` is the single user-facing alert no matter how many
        books matched. `WatchIntentTriggered` is the audit record of the terminal
        transition, so the watch lifecycle stays answerable without joining to
        opportunities.
        """
        if not opportunities:
            return []

        retired = uow.trigger_watch_intents(
            [opp.watch_intent_id for opp in opportunities]
        )

        for opp in opportunities:
            uow.stage_event(
                build_opportunity_identified_event(
                    watch_intent_id=opp.watch_intent_id,
                    opportunity=opp,
                )
            )
            uow.stage_event(
                build_watch_intent_triggered_event(
                    watch_intent_id=opp.watch_intent_id,
                    opportunity=opp,
                )
            )

        return retired

    def evaluate_for_event(self, event_id: str) -> list[Opportunity]:
        started_at = perf_counter()
        inserted_opportunities: list[Opportunity] = []

        self._logger.info(
            "watch_evaluation.started",
            extra={"event_id": event_id},
        )

        try:
            with self._unit_of_work_factory() as uow:
                now = datetime.now(UTC)
                starts_at = uow.get_event_starts_at(event_id)
                if starts_at is not None:
                    sa = starts_at if starts_at.tzinfo else starts_at.replace(tzinfo=UTC)
                    if sa <= now:
                        self._logger.info(
                            "watch_evaluation.skipped_event_started",
                            extra={"event_id": event_id},
                        )
                        return []

                intents = uow.list_active_watch_intents(event_id)

                # Watches past their TTL are retired before evaluation and never
                # evaluated: a reachable target must not fill an expired watch.
                expired = [intent for intent in intents if intent.is_expired_at(now)]
                for retired in uow.expire_watch_intents([i.id for i in expired]):
                    uow.stage_event(
                        build_watch_intent_expired_event(
                            watch_intent_id=retired.id,
                            intent=retired,
                        )
                    )

                live = [intent for intent in intents if not intent.is_expired_at(now)]
                quotes = uow.list_quotes(event_id) if live else []
                evaluated: list[Opportunity] = []

                if live and quotes:
                    market_id_lookup = uow.get_market_id_lookup(event_id)
                    evaluated = self._watch_evaluation_engine.evaluate(
                        watch_intents=live,
                        quotes=quotes,
                        market_id_lookup=market_id_lookup,
                    )

                new_opportunities = evaluated

                if new_opportunities:
                    inserted_opportunities = uow.create_opportunities(new_opportunities)
                    self._notify_and_retire(uow, inserted_opportunities)

            if uow.committed_events:
                self._workflow_event_publisher.publish(uow.committed_events)
        except Exception:
            self._logger.exception(
                "watch_evaluation.failed",
                extra={
                    "event_id": event_id,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise

        self._logger.info(
            "watch_evaluation.completed",
            extra={
                "event_id": event_id,
                "new_opportunity_count": len(inserted_opportunities),
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return inserted_opportunities


def _event_has_started(starts_at: datetime | None, now: datetime) -> bool:
    if starts_at is None:
        return False

    aware = starts_at if starts_at.tzinfo else starts_at.replace(tzinfo=UTC)
    return aware <= now


def _sorted_by_creation(intents: list[WatchIntent], now: datetime) -> list[WatchIntent]:
    return sorted(intents, key=lambda intent: intent.created_at or now)
