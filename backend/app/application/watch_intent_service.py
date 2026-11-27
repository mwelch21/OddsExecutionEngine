import logging
from datetime import UTC, datetime, timedelta
from time import perf_counter

from backend.app.application.book_filter_service import AllBooksResolver
from backend.app.application.ports import (
    BookFilterResolver,
    WatchIntentUnitOfWork,
    WatchIntentUnitOfWorkFactory,
    WorkflowEventPublisher,
)
from backend.app.application.watch_expiry import WatchExpirer
from backend.app.domain.events import (
    build_opportunity_identified_event,
    build_watch_intent_cancelled_event,
    build_watch_intent_created_event,
    build_watch_intent_triggered_event,
)
from backend.app.domain.models import (
    EventLifecycle,
    EventStatus,
    MarketType,
    Opportunity,
    OpportunityWithValidity,
    WatchIntent,
    WatchIntentCreationResult,
    WatchStatus,
    WatchWindow,
)
from backend.app.domain.public_events import build_opportunity_identified_public_event
from backend.app.domain.watch_window import WatchWindowPolicy
from backend.app.engines.event_status_engine import EventStatusEngine
from backend.app.engines.opportunity_validity_engine import OpportunityValidityEngine
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine


class WatchIntentAlreadyTriggeredError(Exception):
    """Raised when a cancel would overwrite a watch's terminal `triggered` status."""

    def __init__(self, watch_intent_id: str) -> None:
        super().__init__(f"Watch intent {watch_intent_id} has already been triggered.")
        self.watch_intent_id = watch_intent_id


class WatchEventNotFoundError(Exception):
    """Raised when a watch names an event that is not stored.

    A watch is made from a stored line board. Refusing an unstored event also
    keeps creation serialized with ingestion: the event row lock is what orders
    a new watch against the status write and its expiry scan.
    """

    def __init__(self, event_id: str) -> None:
        super().__init__(f"Event {event_id} is not stored.")
        self.event_id = event_id


class WatchIntentAlreadyExpiredError(Exception):
    """Raised when a cancel would overwrite a watch's terminal `expired` status.

    An expired watch keeps why it expired; cancelling it would lose that record.
    """

    def __init__(self, watch_intent_id: str) -> None:
        super().__init__(f"Watch intent {watch_intent_id} has already expired.")
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
        event_status_engine: EventStatusEngine | None = None,
        watch_window_policy: WatchWindowPolicy | None = None,
        watch_expirer: WatchExpirer | None = None,
        book_filter_resolver: BookFilterResolver | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._workflow_event_publisher = workflow_event_publisher
        self._watch_evaluation_engine = watch_evaluation_engine
        self._opportunity_validity_engine = opportunity_validity_engine
        self._opportunity_ttl_minutes = opportunity_ttl_minutes
        self._event_status_engine = event_status_engine or EventStatusEngine()
        self._watch_window_policy = watch_window_policy or WatchWindowPolicy()
        self._watch_expirer = watch_expirer or WatchExpirer()
        # The allowed books (#136), resolved at each evaluation: a changed filter
        # applies from the next one, and nothing is re-evaluated on the change.
        self._book_filter_resolver = book_filter_resolver or AllBooksResolver()

    def create_watch_intent(
        self,
        event_id: str,
        market_type: MarketType,
        selection: str,
        target_price: int,
        line: float | None = None,
        expires_at: datetime | None = None,
        window: WatchWindow | None = None,
    ) -> WatchIntentCreationResult:
        """Create a watch and evaluate it at once.

        Without a `window`, `WatchWindowPolicy` picks one from the event's status.
        Raises `WatchEventNotFoundError` for an event that is not stored, and
        `WatchWindowNotAllowedError` for an ended event or a `pre_game` window on
        a live one; nothing is stored then.
        """
        started_at = perf_counter()
        inserted_opportunities: list[Opportunity] = []

        self._logger.info(
            "watch_intent.create.started",
            extra={
                "path": "/api/v1/watch-intents",
                "event_id": event_id,
                "market_type": market_type.value,
                "selection": selection,
            },
        )

        try:
            with self._unit_of_work_factory() as uow:
                # Locked until commit: ingestion's status write takes the same row
                # lock, so it cannot move the event between this read and the
                # insert, and its expiry scan then sees this watch.
                lifecycle = uow.lock_event_lifecycle(event_id)
                if lifecycle is None:
                    raise WatchEventNotFoundError(event_id)
                resolved_window = self._watch_window_policy.resolve(window, lifecycle)
                intent = uow.create_watch_intent(
                    event_id=event_id,
                    market_type=market_type,
                    selection=selection,
                    target_price=target_price,
                    line=line,
                    window=resolved_window,
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
                now = datetime.now(UTC)
                if not intent.is_expired_at(now):
                    fillable = self._event_status_engine.fillable_quotes(
                        lifecycle, uow.list_quotes(event_id), now
                    )
                    quotes = fillable.quotes
                    if fillable.skipped_reason is not None:
                        self._logger.info(
                            "watch_intent.create.evaluation_skipped",
                            extra={
                                "event_id": event_id,
                                "reason": fillable.skipped_reason.value,
                            },
                        )
                    market_id_lookup = uow.get_market_id_lookup(event_id)
                    new_opportunities = self._watch_evaluation_engine.evaluate(
                        watch_intents=[intent],
                        quotes=quotes,
                        market_id_lookup=market_id_lookup,
                        book_filter=self._book_filter_resolver.resolve(),
                    )

                inserted_opportunities, retired = self._fill(uow, new_opportunities)
                # The response reports the watch as the caller will next read it.
                intent = next((r for r in retired if r.id == intent.id), intent)

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
                # A watch whose TTL passed reads as expired, so it cancels as one.
                existing = uow.get_watch_intent(watch_intent_id)
                if existing is not None and existing.effective_status(
                    datetime.now(UTC)
                ) is WatchStatus.EXPIRED:
                    raise WatchIntentAlreadyExpiredError(watch_intent_id)

                # Atomic against concurrent terminal transitions: the write changes
                # only an active (or already cancelled) row. `triggered` and
                # `expired` are terminal; overwriting either would erase why the
                # watch ended.
                intent = uow.cancel_watch_intent(watch_intent_id)
                if intent.status is WatchStatus.TRIGGERED:
                    raise WatchIntentAlreadyTriggeredError(watch_intent_id)
                if intent.status is WatchStatus.EXPIRED:
                    raise WatchIntentAlreadyExpiredError(watch_intent_id)
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
        event that has not ended (#38).
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

            lifecycles = {
                event: uow.get_event_lifecycle(event)
                for event in {intent.event_id for intent in intents}
            }

        return _sorted_by_creation(
            [
                intent
                for intent in intents
                if _not_ended(lifecycles.get(intent.event_id))
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

    def _fill(
        self,
        uow: WatchIntentUnitOfWork,
        opportunities: list[Opportunity],
    ) -> tuple[list[Opportunity], list[WatchIntent]]:
        """Retire each watch that filled, then record and notify its opportunity.

        The trigger comes first and moves only a still-active watch. A watch a
        concurrent DELETE or expiry just retired comes back unchanged, so it gets
        no opportunity and no notification. Returns the opportunities inserted and
        the watches triggered, all in the caller's transaction.
        """
        if not opportunities:
            return [], []
        retired = uow.trigger_watch_intents([opp.watch_intent_id for opp in opportunities])
        armed = {intent.id for intent in retired}
        if not armed:
            return [], []
        inserted = uow.create_opportunities(
            [opp for opp in opportunities if opp.watch_intent_id in armed]
        )
        self._notify(uow, inserted)
        return inserted, retired

    def _notify(
        self,
        uow: WatchIntentUnitOfWork,
        opportunities: list[Opportunity],
    ) -> None:
        """Notify once per opportunity the DB accepted.

        Only opportunities the DB actually accepted reach here, and they commit in
        the same transaction as their watch's `triggered` transition, so a row
        cannot exist without its watch retired.

        `OpportunityIdentified` is the single user-facing alert no matter how many
        books matched. Its public counterpart, `opportunity.identified.v1`, is staged
        in the same transaction, so the public outbox can never hold an event for a
        rolled-back opportunity nor miss one for a committed one (ADR-014).
        `WatchIntentTriggered` is the audit record of the terminal transition, so
        the watch lifecycle stays answerable without joining to opportunities.
        """
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
            uow.stage_public_event(
                build_opportunity_identified_public_event(
                    opportunity=opp,
                    valid_for=timedelta(minutes=self._opportunity_ttl_minutes),
                    context=uow.get_opportunity_event_context(opp),
                )
            )


    def evaluate_for_event(self, event_id: str) -> list[Opportunity]:
        started_at = perf_counter()
        inserted_opportunities: list[Opportunity] = []

        self._logger.info(
            "watch_evaluation.started",
            extra={"event_id": event_id},
        )

        try:
            with self._unit_of_work_factory() as uow:
                # Locked until commit, so the event cannot end or start between
                # this check and the opportunity insert.
                lifecycle = uow.lock_event_lifecycle(event_id)
                # Read after the lock: time spent waiting for it counts.
                now = datetime.now(UTC)
                intents = uow.list_active_watch_intents(event_id)

                # Retired before evaluation, never evaluated: a passed TTL, or an
                # event status that closed the window (ADR-017). Ingestion expires
                # on the status write; this is the backstop for an event nobody
                # refreshed since.
                retired = {
                    intent.id
                    for intent in self._watch_expirer.expire(
                        uow,
                        intents,
                        {} if lifecycle is None else {event_id: lifecycle},
                        now,
                    )
                }
                armed = [intent for intent in intents if intent.id not in retired]

                # Live events evaluate on their live lines; ended ones produce
                # nothing (#38). Checked before any quote is read.
                skipped = self._event_status_engine.skip_reason(lifecycle, now)
                if skipped is not None:
                    self._logger.info(
                        "watch_evaluation.skipped",
                        extra={"event_id": event_id, "reason": skipped.value},
                    )
                    armed = []

                # Quotes are read only when an armed watch could use them.
                quotes = (
                    self._event_status_engine.fillable_quotes(
                        lifecycle, uow.list_quotes(event_id), now
                    ).quotes
                    if armed
                    else []
                )

                if armed and quotes:
                    new_opportunities = self._watch_evaluation_engine.evaluate(
                        watch_intents=armed,
                        quotes=quotes,
                        market_id_lookup=uow.get_market_id_lookup(event_id),
                        book_filter=self._book_filter_resolver.resolve(),
                    )
                    inserted_opportunities, _ = self._fill(uow, new_opportunities)

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


def _not_ended(lifecycle: EventLifecycle | None) -> bool:
    # A watch on a started event nobody has observed since kickoff stays listed:
    # the next refresh may find it live, and then it can fill.
    return lifecycle is None or lifecycle.status is not EventStatus.ENDED


def _sorted_by_creation(intents: list[WatchIntent], now: datetime) -> list[WatchIntent]:
    return sorted(intents, key=lambda intent: intent.created_at or now)
