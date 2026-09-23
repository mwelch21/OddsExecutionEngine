from datetime import UTC, datetime, timedelta

from backend.app.application.watch_intent_service import WatchIntentService
from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import (
    MarketType,
    MatchingQuote,
    Opportunity,
    Quote,
    WatchIntent,
    WatchStatus,
)
from backend.app.engines.opportunity_validity_engine import OpportunityValidityEngine
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.recommendation_engine import RecommendationEngine
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
        self.triggered_ids: list[str] = []

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

    def trigger_watch_intents(self, watch_intent_ids: list[str]) -> list[WatchIntent]:
        self.triggered_ids.extend(watch_intent_ids)
        wanted = set(watch_intent_ids)
        triggered = [
            intent.model_copy(update={"status": WatchStatus.TRIGGERED})
            for intent in self._active_intents
            if intent.id in wanted
        ]
        self._active_intents = [
            intent for intent in self._active_intents if intent.id not in wanted
        ]
        return triggered

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

    def stage_event(self, event: WorkflowEvent) -> None:
        self._staged_events.append(event)

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]:
        return self._committed_events


class StubWatchEvaluationEngine(WatchEvaluationEngine):
    def __init__(self, opportunities: list[Opportunity]) -> None:
        price_comparison = PriceComparisonService()
        super().__init__(price_comparison, RecommendationEngine(price_comparison))
        self._opportunities = opportunities

    def evaluate(
        self,
        watch_intents: list[WatchIntent],
        quotes: list[Quote],
        market_id_lookup: dict[tuple[str, str, str, float | None], str],
    ) -> list[Opportunity]:
        return list(self._opportunities)


def test_create_watch_intent_returns_a_triggered_watch_when_it_fills_at_once() -> None:
    intent = WatchIntent(
        id="wi-1",
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )
    inserted = _make_opportunity("opp-1", intent.id, "DraftKings")
    uow = RecordingWatchIntentUnitOfWork(
        created_intent=intent,
        inserted_opportunities=[inserted],
    )
    publisher = InMemoryWorkflowEventPublisher()
    service = WatchIntentService(
        unit_of_work_factory=lambda: uow,
        workflow_event_publisher=publisher,
        watch_evaluation_engine=StubWatchEvaluationEngine([inserted]),
        opportunity_validity_engine=OpportunityValidityEngine(),
        opportunity_ttl_minutes=5,
    )

    result = service.create_watch_intent(
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )

    assert result.watch_intent.id == "wi-1"
    assert result.watch_intent.status is WatchStatus.TRIGGERED
    # The opportunity rides back with the watch: the same transaction already knew it.
    assert result.opportunity is not None
    assert result.opportunity.id == "opp-1"
    assert [event.event_type for event in publisher.published_events] == [
        "WatchIntentCreated",
        "OpportunityIdentified",
        "WatchIntentTriggered",
    ]
    assert publisher.published_events[1].aggregate_id == "opp-1"
    assert publisher.published_events[2].aggregate_id == "wi-1"
    assert uow.triggered_ids == ["wi-1"]


def test_evaluate_for_event_notifies_once_however_many_books_matched() -> None:
    intent = WatchIntent(
        id="wi-1",
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )
    opportunity = Opportunity(
        id="opp-1",
        watch_intent_id=intent.id,
        event_id="event-1",
        market_id="market-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
        best_sportsbook="DraftKings",
        best_price=125,
        matching_quotes=[
            MatchingQuote(sportsbook="DraftKings", price=125),
            MatchingQuote(sportsbook="FanDuel", price=125),
            MatchingQuote(sportsbook="Caesars", price=122),
        ],
    )
    uow = RecordingWatchIntentUnitOfWork(
        created_intent=intent,
        active_intents=[intent],
        inserted_opportunities=[opportunity],
        starts_at=datetime.now(UTC) + timedelta(days=1),
    )
    publisher = InMemoryWorkflowEventPublisher()
    service = WatchIntentService(
        unit_of_work_factory=lambda: uow,
        workflow_event_publisher=publisher,
        watch_evaluation_engine=StubWatchEvaluationEngine([opportunity]),
        opportunity_validity_engine=OpportunityValidityEngine(),
        opportunity_ttl_minutes=5,
    )

    result = service.evaluate_for_event("event-1")

    assert [opp.id for opp in result] == ["opp-1"]
    identified = [
        event
        for event in publisher.published_events
        if event.event_type == "OpportunityIdentified"
    ]
    assert len(identified) == 1
    assert uow.triggered_ids == ["wi-1"]


def test_evaluate_for_event_does_not_re_evaluate_a_triggered_watch() -> None:
    intent = WatchIntent(
        id="wi-1",
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )
    opportunity = _make_opportunity("opp-1", intent.id, "DraftKings")
    uow = RecordingWatchIntentUnitOfWork(
        created_intent=intent,
        active_intents=[intent],
        inserted_opportunities=[opportunity],
        starts_at=datetime.now(UTC) + timedelta(days=1),
    )
    publisher = InMemoryWorkflowEventPublisher()
    service = WatchIntentService(
        unit_of_work_factory=lambda: uow,
        workflow_event_publisher=publisher,
        watch_evaluation_engine=StubWatchEvaluationEngine([opportunity]),
        opportunity_validity_engine=OpportunityValidityEngine(),
        opportunity_ttl_minutes=5,
    )

    service.evaluate_for_event("event-1")
    second_pass = service.evaluate_for_event("event-1")

    # The fake drops triggered watches from the active set, exactly as
    # list_active_watch_intents does once the status is stored.
    assert second_pass == []
    assert uow.triggered_ids == ["wi-1"]


def test_evaluate_for_event_skips_events_and_triggers_when_the_db_rejects_the_insert() -> (
    None
):
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
    assert uow.triggered_ids == []
    assert [opp.id for opp in uow.created_batches[0]] == ["opp-1"]


def _make_opportunity(
    opportunity_id: str,
    watch_intent_id: str,
    best_sportsbook: str,
) -> Opportunity:
    return Opportunity(
        id=opportunity_id,
        watch_intent_id=watch_intent_id,
        event_id="event-1",
        market_id="market-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
        best_sportsbook=best_sportsbook,
        best_price=125,
        matching_quotes=[MatchingQuote(sportsbook=best_sportsbook, price=125)],
    )
