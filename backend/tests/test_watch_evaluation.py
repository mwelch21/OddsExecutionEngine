from datetime import UTC, datetime, timedelta

import pytest

from backend.app.application.watch_evaluation_service import WatchEvaluationService
from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import (
    MarketType,
    OpportunitySignal,
    Quote,
    WatchIntent,
    WatchStatus,
)
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine
from backend.app.infrastructure.publishers.in_memory_publisher import (
    InMemoryWorkflowEventPublisher,
)

EVENT_ID = "event-1"


class RecordingWatchEvaluationUnitOfWork:
    def __init__(
        self,
        *,
        watches: list[WatchIntent] | None = None,
        quotes: list[Quote] | None = None,
        fail_on_create_opportunity: bool = False,
    ) -> None:
        self.watches = list(watches or [])
        self.quotes = list(quotes or [])
        self.opportunities: list[OpportunitySignal] = []
        self.status_updates: list[tuple[str, WatchStatus]] = []
        self._fail_on_create_opportunity = fail_on_create_opportunity
        self._staged_events: list[WorkflowEvent] = []
        self._committed_events: tuple[WorkflowEvent, ...] = ()

    def __enter__(self) -> "RecordingWatchEvaluationUnitOfWork":
        self._staged_events = []
        self._committed_events = ()
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
            self.opportunities = []
            self.status_updates = []
        self._staged_events = []

    def list_active_watch_intents(self, event_id: str) -> list[WatchIntent]:
        return [
            watch
            for watch in self.watches
            if watch.event_id == event_id and watch.status is WatchStatus.ACTIVE
        ]

    def list_quotes(self, event_id: str) -> list[Quote]:
        return [quote for quote in self.quotes if quote.event_id == event_id]

    def create_opportunity_signal(self, opportunity_signal: OpportunitySignal) -> None:
        if self._fail_on_create_opportunity:
            raise RuntimeError("opportunity persistence failed")
        self.opportunities.append(opportunity_signal)

    def update_watch_intent_status(self, watch_intent_id: str, status: WatchStatus) -> None:
        self.status_updates.append((watch_intent_id, status))

    def list_opportunity_signals(self, *, event_id: str | None = None) -> list[OpportunitySignal]:
        return [
            opportunity
            for opportunity in self.opportunities
            if event_id is None or opportunity.event_id == event_id
        ]

    def get_opportunity_signal(self, opportunity_signal_id: str) -> OpportunitySignal | None:
        return next(
            (
                opportunity
                for opportunity in self.opportunities
                if opportunity.id == opportunity_signal_id
            ),
            None,
        )

    def stage_event(self, event: WorkflowEvent) -> None:
        self._staged_events.append(event)

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]:
        return self._committed_events


def _build_service(
    unit_of_work: RecordingWatchEvaluationUnitOfWork,
) -> tuple[WatchEvaluationService, InMemoryWorkflowEventPublisher]:
    publisher = InMemoryWorkflowEventPublisher()
    service = WatchEvaluationService(
        unit_of_work_factory=lambda: unit_of_work,
        watch_evaluation_engine=WatchEvaluationEngine(
            quote_matching_engine=QuoteMatchingEngine(),
            recommendation_engine=RecommendationEngine(PriceComparisonService()),
            price_comparison_service=PriceComparisonService(),
        ),
        workflow_event_publisher=publisher,
    )
    return service, publisher


def _build_watch(
    *,
    watch_id: str = "watch-1",
    target_price: int = 120,
    expires_at: datetime | None = None,
) -> WatchIntent:
    return WatchIntent(
        id=watch_id,
        event_id=EVENT_ID,
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=target_price,
        expires_at=expires_at,
        status=WatchStatus.ACTIVE,
        created_at=datetime.now(UTC),
    )


def _build_quote(price: int = 125) -> Quote:
    return Quote(
        event_id=EVENT_ID,
        sportsbook="BookA",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        price=price,
    )


def test_triggered_watch_creates_opportunity_and_publishes_event() -> None:
    unit_of_work = RecordingWatchEvaluationUnitOfWork(
        watches=[_build_watch(target_price=120)],
        quotes=[_build_quote(price=125)],
    )
    service, publisher = _build_service(unit_of_work)

    summary = service.evaluate_event(EVENT_ID)

    assert summary.event_id == EVENT_ID
    assert summary.evaluated_watch_count == 1
    assert summary.triggered_watch_count == 1
    assert summary.expired_watch_count == 0
    assert summary.emitted_event_types == ["TargetPriceBecameFillable"]

    opportunity = unit_of_work.opportunities[0]
    assert opportunity.watch_intent_id == "watch-1"
    assert opportunity.event_id == EVENT_ID
    assert opportunity.matched_price == 125
    assert opportunity.target_price == 120
    assert opportunity.sportsbook == "BookA"
    assert unit_of_work.status_updates == [("watch-1", WatchStatus.TRIGGERED)]
    assert [event.event_type for event in publisher.published_events] == [
        "TargetPriceBecameFillable"
    ]
    assert publisher.published_events[0].aggregate_id == opportunity.id


def test_expired_watch_is_marked_expired_and_publishes_event() -> None:
    unit_of_work = RecordingWatchEvaluationUnitOfWork(
        watches=[
            _build_watch(
                watch_id="expired-watch",
                target_price=100,
                expires_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        ],
        quotes=[_build_quote(price=125)],
    )
    service, publisher = _build_service(unit_of_work)

    summary = service.evaluate_event(EVENT_ID)

    assert summary.triggered_watch_count == 0
    assert summary.expired_watch_count == 1
    assert unit_of_work.opportunities == []
    assert unit_of_work.status_updates == [("expired-watch", WatchStatus.EXPIRED)]
    assert [event.event_type for event in publisher.published_events] == ["WatchIntentExpired"]


def test_unfilled_watch_stays_active_and_emits_no_events() -> None:
    unit_of_work = RecordingWatchEvaluationUnitOfWork(
        watches=[_build_watch(target_price=200)],
        quotes=[_build_quote(price=125)],
    )
    service, publisher = _build_service(unit_of_work)

    summary = service.evaluate_event(EVENT_ID)

    assert summary.evaluated_watch_count == 1
    assert summary.triggered_watch_count == 0
    assert summary.emitted_event_types == []
    assert unit_of_work.status_updates == []
    assert publisher.published_events == []


def test_evaluation_without_active_watches_emits_no_events() -> None:
    unit_of_work = RecordingWatchEvaluationUnitOfWork(quotes=[_build_quote()])
    service, publisher = _build_service(unit_of_work)

    summary = service.evaluate_event(EVENT_ID)

    assert summary.evaluated_watch_count == 0
    assert summary.emitted_event_types == []
    assert publisher.published_events == []


def test_evaluation_does_not_publish_when_transaction_fails() -> None:
    unit_of_work = RecordingWatchEvaluationUnitOfWork(
        watches=[_build_watch(target_price=120)],
        quotes=[_build_quote(price=125)],
        fail_on_create_opportunity=True,
    )
    service, publisher = _build_service(unit_of_work)

    with pytest.raises(RuntimeError, match="opportunity persistence failed"):
        service.evaluate_event(EVENT_ID)

    assert publisher.published_events == []
    assert unit_of_work.committed_events == ()


def test_opportunity_reads_are_exposed_through_the_service() -> None:
    unit_of_work = RecordingWatchEvaluationUnitOfWork(
        watches=[_build_watch(target_price=120)],
        quotes=[_build_quote(price=125)],
    )
    service, _ = _build_service(unit_of_work)
    service.evaluate_event(EVENT_ID)
    created = unit_of_work.opportunities[0]

    assert [opportunity.id for opportunity in service.list_opportunities()] == [created.id]
    assert service.list_opportunities(event_id="other-event") == []
    assert service.get_opportunity(created.id) == created
    assert service.get_opportunity("missing") is None
