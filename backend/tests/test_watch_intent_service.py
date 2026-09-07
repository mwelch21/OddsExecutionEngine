from datetime import UTC, datetime, timedelta

from backend.app.application.watch_intent_service import WatchIntentService
from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import (
    MarketType,
    Opportunity,
    Quote,
    WatchIntent,
    WatchStatus,
)
from backend.app.engines.opportunity_validity_engine import OpportunityValidityEngine
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine
from backend.app.infrastructure.publishers.in_memory_publisher import (
    InMemoryWorkflowEventPublisher,
)


class RecordingWatchIntentUnitOfWork:
    def __init__(
        self,
        *,
        created_intent: WatchIntent,
        active_intents: list[WatchIntent] | None = None,
        inserted_opportunities: list[Opportunity] | None = None,
        starts_at: datetime | None = None,
    ) -> None:
        self._created_intent = created_intent
        self._active_intents = active_intents or [created_intent]
        self._inserted_opportunities = inserted_opportunities or []
        self._starts_at = starts_at
        self._staged_events: list[WorkflowEvent] = []
        self._committed_events: tuple[WorkflowEvent, ...] = ()
        self.created_batches: list[list[Opportunity]] = []

        self.expired_ids: list[str] = []

    def __enter__(self) -> "RecordingWatchIntentUnitOfWork":
        self._staged_events = []
        self._committed_events = ()
        self.created_batches = []
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        if exc_type is None:
            self._committed_events = tuple(self._staged_events)
        else:
            self._committed_events = ()
        self._staged_events = []

    def create_watch_intent(
        self,
        event_id: str,
        market_type: MarketType,
        selection: str,
        target_price: int,
        line: float | None,
        expires_at: datetime | None = None,
    ) -> WatchIntent:
        return self._created_intent

    def cancel_watch_intent(self, watch_intent_id: str) -> WatchIntent:
        raise NotImplementedError

    def expire_watch_intents(self, watch_intent_ids: list[str]) -> list[WatchIntent]:
        self.expired_ids.extend(watch_intent_ids)
        expired = [
            intent.model_copy(update={"status": WatchStatus.EXPIRED})
            for intent in self._active_intents
            if intent.id in set(watch_intent_ids)
        ]
        self._active_intents = [
            intent
            for intent in self._active_intents
            if intent.id not in set(watch_intent_ids)
        ]
        return expired

    def get_watch_intent(self, watch_intent_id: str) -> WatchIntent | None:
        return next(
            (intent for intent in self._active_intents if intent.id == watch_intent_id),
            None,
        )

    def list_watch_intents(
        self,
        event_id: str | None = None,
        status: WatchStatus | None = None,
    ) -> list[WatchIntent]:
        return [
            intent
            for intent in self._active_intents
            if (event_id is None or intent.event_id == event_id)
            and (status is None or intent.status is status)
        ]

    def get_opportunity(self, opportunity_id: str) -> Opportunity | None:
        return None

    def list_active_watch_intents(
        self, event_id: str | None = None
    ) -> list[WatchIntent]:
        return list(self._active_intents)

    def list_quotes(self, event_id: str) -> list[Quote]:
        return [
            Quote(
                event_id="event-1",
                sportsbook="DraftKings",
                market_type=MarketType.MONEYLINE,
                selection="knicks",
                price=125,
            )
        ]

    def get_market_id_lookup(
        self, event_id: str
    ) -> dict[tuple[str, str, str, float | None], str]:
        return {}

    def create_opportunities(
        self, opportunities: list[Opportunity]
    ) -> list[Opportunity]:
        self.created_batches.append(list(opportunities))
        return list(self._inserted_opportunities)

    def list_opportunities(self, event_id: str | None = None) -> list[Opportunity]:
        raise NotImplementedError

    def get_latest_quote_times(
        self, opportunities: list[Opportunity]
    ) -> list[tuple[Opportunity, datetime | None]]:
        raise NotImplementedError

    def get_event_starts_at(self, event_external_id: str) -> datetime | None:
        return self._starts_at

    def list_existing_opportunity_keys(
        self, watch_intent_ids: list[str]
    ) -> set[tuple[str, str, str]]:
        return set()

    def stage_event(self, event: WorkflowEvent) -> None:
        self._staged_events.append(event)

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]:
        return self._committed_events


class StubWatchEvaluationEngine(WatchEvaluationEngine):
    def __init__(self, opportunities: list[Opportunity]) -> None:
        super().__init__(PriceComparisonService())
        self._opportunities = opportunities

    def evaluate(
        self,
        watch_intents: list[WatchIntent],
        quotes: list[Quote],
        market_id_lookup: dict[tuple[str, str, str, float | None], str],
        existing_opportunity_keys: set[tuple[str, str, str]] | None = None,
    ) -> list[Opportunity]:
        return list(self._opportunities)


def test_create_watch_intent_emits_events_only_for_inserted_opportunities() -> None:
    intent = WatchIntent(
        id="wi-1",
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )
    inserted = _make_opportunity("opp-1", intent.id, "DraftKings")
    duplicate = _make_opportunity("opp-2", intent.id, "FanDuel")
    uow = RecordingWatchIntentUnitOfWork(
        created_intent=intent,
        inserted_opportunities=[inserted],
    )
    publisher = InMemoryWorkflowEventPublisher()
    service = WatchIntentService(
        unit_of_work_factory=lambda: uow,
        workflow_event_publisher=publisher,
        watch_evaluation_engine=StubWatchEvaluationEngine([inserted, duplicate]),
        opportunity_validity_engine=OpportunityValidityEngine(),
        opportunity_ttl_minutes=5,
    )

    result = service.create_watch_intent(
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )

    assert result.id == "wi-1"
    assert [event.event_type for event in publisher.published_events] == [
        "WatchIntentCreated",
        "OpportunityIdentified",
    ]
    assert publisher.published_events[1].aggregate_id == "opp-1"
    assert [opp.id for opp in uow.created_batches[0]] == ["opp-1", "opp-2"]


def test_evaluate_for_event_skips_events_when_db_rejects_all_duplicates() -> None:
    intent = WatchIntent(
        id="wi-1",
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )
    candidate = _make_opportunity("opp-1", intent.id, "DraftKings")
    uow = RecordingWatchIntentUnitOfWork(
        created_intent=intent,
        active_intents=[intent],
        inserted_opportunities=[],
        starts_at=datetime.now(UTC) + timedelta(days=1),
    )
    publisher = InMemoryWorkflowEventPublisher()
    service = WatchIntentService(
        unit_of_work_factory=lambda: uow,
        workflow_event_publisher=publisher,
        watch_evaluation_engine=StubWatchEvaluationEngine([candidate]),
        opportunity_validity_engine=OpportunityValidityEngine(),
        opportunity_ttl_minutes=5,
    )

    result = service.evaluate_for_event("event-1")

    assert result == []
    assert publisher.published_events == []
    assert [opp.id for opp in uow.created_batches[0]] == ["opp-1"]


def _make_opportunity(
    opportunity_id: str,
    watch_intent_id: str,
    sportsbook: str,
) -> Opportunity:
    return Opportunity(
        id=opportunity_id,
        watch_intent_id=watch_intent_id,
        event_id="event-1",
        market_id="market-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
        sportsbook=sportsbook,
        matched_price=125,
    )
