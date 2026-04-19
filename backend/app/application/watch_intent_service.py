import logging
from datetime import UTC, datetime
from time import perf_counter

from backend.app.application.ports import (
    WatchIntentUnitOfWorkFactory,
    WorkflowEventPublisher,
)
from backend.app.domain.events import (
    build_opportunity_identified_event,
    build_watch_intent_cancelled_event,
    build_watch_intent_created_event,
)
from backend.app.domain.models import (
    MarketType,
    Opportunity,
    OpportunityWithValidity,
    WatchIntent,
)
from backend.app.engines.opportunity_validity_engine import OpportunityValidityEngine
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine


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
    ) -> WatchIntent:
        started_at = perf_counter()

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
                )

                uow.stage_event(
                    build_watch_intent_created_event(
                        watch_intent_id=intent.id,
                        intent=intent,
                    )
                )

                # Immediate evaluation against current quotes
                quotes = uow.list_quotes(event_id)
                market_id_lookup = uow.get_market_id_lookup(event_id)
                new_opportunities = self._watch_evaluation_engine.evaluate(
                    watch_intents=[intent],
                    quotes=quotes,
                    market_id_lookup=market_id_lookup,
                )

                if new_opportunities:
                    uow.create_opportunities(new_opportunities)
                    for opp in new_opportunities:
                        uow.stage_event(
                            build_opportunity_identified_event(
                                watch_intent_id=intent.id,
                                opportunity=opp,
                            )
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
                "opportunity_count": len(new_opportunities),
                "event_count": len(uow.committed_events),
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return intent

    def cancel_watch_intent(self, watch_intent_id: str) -> WatchIntent:
        started_at = perf_counter()

        self._logger.info(
            "watch_intent.cancel.started",
            extra={"watch_intent_id": watch_intent_id},
        )

        try:
            with self._unit_of_work_factory() as uow:
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

    def list_watch_intents(
        self, event_id: str | None = None
    ) -> list[WatchIntent]:
        now = datetime.now(UTC)
        with self._unit_of_work_factory() as uow:
            intents = uow.list_active_watch_intents(event_id)
            if not intents:
                return []

            # Batch-check event start times to filter expired intents
            event_ids = {i.event_id for i in intents}
            starts_at_map: dict[str, datetime | None] = {}
            for eid in event_ids:
                starts_at_map[eid] = uow.get_event_starts_at(eid)

        active: list[WatchIntent] = []
        for intent in intents:
            starts_at = starts_at_map.get(intent.event_id)
            if starts_at is None:
                active.append(intent)
                continue
            # Handle naive datetimes from SQLite
            sa = starts_at if starts_at.tzinfo else starts_at.replace(tzinfo=UTC)
            if sa > now:
                active.append(intent)
        return active

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

    def evaluate_for_event(self, event_id: str) -> list[Opportunity]:
        started_at = perf_counter()
        new_opportunities: list[Opportunity] = []

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
                if not intents:
                    return []

                quotes = uow.list_quotes(event_id)
                if not quotes:
                    return []

                market_id_lookup = uow.get_market_id_lookup(event_id)
                intent_ids = [i.id for i in intents]
                existing_keys = uow.list_existing_opportunity_keys(intent_ids)

                new_opportunities = self._watch_evaluation_engine.evaluate(
                    watch_intents=intents,
                    quotes=quotes,
                    market_id_lookup=market_id_lookup,
                    existing_opportunity_keys=existing_keys,
                )

                if new_opportunities:
                    uow.create_opportunities(new_opportunities)
                    for opp in new_opportunities:
                        uow.stage_event(
                            build_opportunity_identified_event(
                                watch_intent_id=opp.watch_intent_id,
                                opportunity=opp,
                            )
                        )

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
                "new_opportunity_count": len(new_opportunities),
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return new_opportunities
