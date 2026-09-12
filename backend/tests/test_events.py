import pytest

from backend.app.application.recommendation_service import RecommendationService
from backend.app.domain.events import (
    WorkflowEvent,
    build_execution_recommendation_generated_event,
    build_opportunity_identified_event,
    build_order_intent_submitted_event,
    build_watch_intent_cancelled_event,
    build_watch_intent_created_event,
    build_watch_intent_triggered_event,
)
from backend.app.domain.models import (
    ExecutionRecommendation,
    MarketType,
    MatchingQuote,
    Opportunity,
    OrderIntent,
    Quote,
    WatchIntent,
)
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.infrastructure.publishers.in_memory_publisher import (
    InMemoryWorkflowEventPublisher,
)


class RecordingRecommendationUnitOfWork:
    def __init__(
        self,
        *,
        quotes: list[Quote],
        fail_on_recommendation_write: bool = False,
    ) -> None:
        self._quotes = quotes
        self._fail_on_recommendation_write = fail_on_recommendation_write
        self._staged_events: list[WorkflowEvent] = []
        self._committed_events: tuple[WorkflowEvent, ...] = ()
        self.created_order_intent_ids: list[str] = []
        self.created_recommendation_ids: list[str] = []

    def __enter__(self) -> "RecordingRecommendationUnitOfWork":
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
        self._staged_events = []

    def create_order_intent(self, intent: OrderIntent) -> str:
        order_intent_id = "order-intent-1"
        self.created_order_intent_ids.append(order_intent_id)
        return order_intent_id

    def list_quotes(self, event_id: str) -> list[Quote]:
        return list(self._quotes)

    def create_execution_recommendation(
        self,
        order_intent_id: str,
        recommendation: ExecutionRecommendation,
    ) -> str:
        if self._fail_on_recommendation_write:
            raise RuntimeError("recommendation write failed")

        recommendation_id = "execution-recommendation-1"
        self.created_recommendation_ids.append(recommendation_id)
        return recommendation_id

    def stage_event(self, event: WorkflowEvent) -> None:
        self._staged_events.append(event)

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]:
        return self._committed_events


def test_build_order_intent_submitted_event_contains_deterministic_payload() -> None:
    intent = OrderIntent(
        event_id="event-1",
        market_type=MarketType.TOTAL,
        selection="over",
        line=221.5,
        target_price=-110,
    )

    event = build_order_intent_submitted_event(
        order_intent_id="order-intent-1",
        intent=intent,
    )

    assert event.event_type == "OrderIntentSubmitted"
    assert event.aggregate_id == "order-intent-1"
    assert event.workflow_id == "order-intent-1"
    assert event.payload.model_dump() == {
        "event_id": "event-1",
        "market_type": "total",
        "selection": "over",
        "target_price": -110,
        "line": 221.5,
    }


def test_build_execution_recommendation_generated_event_contains_summary_payload() -> None:
    recommendation = ExecutionRecommendation(
        intent=OrderIntent(
            event_id="event-1",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            target_price=120,
        ),
        fillable=True,
        best_quote=Quote(
            event_id="event-1",
            sportsbook="DraftKings",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=125,
        ),
        ranked_quotes=[],
        nearest_miss=None,
        matched_quote_count=3,
    )

    event = build_execution_recommendation_generated_event(
        order_intent_id="order-intent-1",
        recommendation_id="recommendation-1",
        recommendation=recommendation,
    )

    assert event.event_type == "ExecutionRecommendationGenerated"
    assert event.aggregate_id == "recommendation-1"
    assert event.workflow_id == "order-intent-1"
    assert event.payload.model_dump() == {
        "fillable": True,
        "matched_quote_count": 3,
        "best_quote": {
            "sportsbook": "DraftKings",
            "selection": "knicks",
            "price": 125,
            "line": None,
        },
        "nearest_miss": None,
    }


def test_recommendation_service_publishes_events_after_successful_commit() -> None:
    intent = OrderIntent(
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )
    quote = Quote(
        event_id="event-1",
        sportsbook="DraftKings",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        price=125,
    )
    unit_of_work = RecordingRecommendationUnitOfWork(quotes=[quote])
    publisher = InMemoryWorkflowEventPublisher()
    service = RecommendationService(
        unit_of_work_factory=lambda: unit_of_work,
        workflow_event_publisher=publisher,
        quote_matching_engine=QuoteMatchingEngine(),
        recommendation_engine=RecommendationEngine(PriceComparisonService()),
    )

    recommendation = service.recommend(intent)

    assert recommendation.fillable is True
    assert [event.event_type for event in publisher.published_events] == [
        "OrderIntentSubmitted",
        "ExecutionRecommendationGenerated",
    ]
    assert [event.workflow_id for event in publisher.published_events] == [
        "order-intent-1",
        "order-intent-1",
    ]


def test_recommendation_service_does_not_publish_events_on_rollback() -> None:
    intent = OrderIntent(
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )
    quote = Quote(
        event_id="event-1",
        sportsbook="DraftKings",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        price=125,
    )
    unit_of_work = RecordingRecommendationUnitOfWork(
        quotes=[quote],
        fail_on_recommendation_write=True,
    )
    publisher = InMemoryWorkflowEventPublisher()
    service = RecommendationService(
        unit_of_work_factory=lambda: unit_of_work,
        workflow_event_publisher=publisher,
        quote_matching_engine=QuoteMatchingEngine(),
        recommendation_engine=RecommendationEngine(PriceComparisonService()),
    )

    try:
        service.recommend(intent)
    except RuntimeError as exc:
        assert str(exc) == "recommendation write failed"
    else:
        raise AssertionError("Expected recommendation service to propagate rollback error.")

    assert publisher.published_events == []
    assert unit_of_work.committed_events == ()


def test_recommendation_service_logs_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = OrderIntent(
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )
    quote = Quote(
        event_id="event-1",
        sportsbook="DraftKings",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        price=125,
    )
    recorded_messages: list[str] = []

    def record_info(message: str, *args: object, **kwargs: object) -> None:
        recorded_messages.append(message)

    def record_exception(message: str, *args: object, **kwargs: object) -> None:
        recorded_messages.append(message)

    monkeypatch.setattr(RecommendationService._logger, "info", record_info)
    monkeypatch.setattr(RecommendationService._logger, "exception", record_exception)

    success_uow = RecordingRecommendationUnitOfWork(quotes=[quote])
    success_publisher = InMemoryWorkflowEventPublisher()
    success_service = RecommendationService(
        unit_of_work_factory=lambda: success_uow,
        workflow_event_publisher=success_publisher,
        quote_matching_engine=QuoteMatchingEngine(),
        recommendation_engine=RecommendationEngine(PriceComparisonService()),
    )

    success_service.recommend(intent)

    assert "recommendation.started" in recorded_messages
    assert "recommendation.completed" in recorded_messages

    failing_uow = RecordingRecommendationUnitOfWork(
        quotes=[quote],
        fail_on_recommendation_write=True,
    )
    failing_service = RecommendationService(
        unit_of_work_factory=lambda: failing_uow,
        workflow_event_publisher=InMemoryWorkflowEventPublisher(),
        quote_matching_engine=QuoteMatchingEngine(),
        recommendation_engine=RecommendationEngine(PriceComparisonService()),
    )

    with pytest.raises(RuntimeError, match="recommendation write failed"):
        failing_service.recommend(intent)

    assert "recommendation.failed" in recorded_messages


def test_build_watch_intent_created_event_contains_deterministic_payload() -> None:
    intent = WatchIntent(
        id="wi-1",
        event_id="event-1",
        market_type=MarketType.SPREAD,
        selection="knicks",
        target_price=-110,
        line=5.5,
    )

    event = build_watch_intent_created_event(watch_intent_id="wi-1", intent=intent)

    assert event.event_type == "WatchIntentCreated"
    assert event.aggregate_id == "wi-1"
    assert event.workflow_id == "wi-1"
    assert event.payload.model_dump() == {
        "event_id": "event-1",
        "market_type": "spread",
        "selection": "knicks",
        "target_price": -110,
        "line": 5.5,
    }


def test_build_watch_intent_cancelled_event_contains_deterministic_payload() -> None:
    intent = WatchIntent(
        id="wi-1",
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )

    event = build_watch_intent_cancelled_event(watch_intent_id="wi-1", intent=intent)

    assert event.event_type == "WatchIntentCancelled"
    assert event.aggregate_id == "wi-1"
    assert event.payload.model_dump() == {
        "event_id": "event-1",
        "market_type": "moneyline",
        "selection": "knicks",
    }


def _opportunity() -> Opportunity:
    return Opportunity(
        id="opp-1",
        watch_intent_id="wi-1",
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
        ],
    )


def test_build_opportunity_identified_event_contains_deterministic_payload() -> None:
    event = build_opportunity_identified_event(
        watch_intent_id="wi-1", opportunity=_opportunity()
    )

    assert event.event_type == "OpportunityIdentified"
    assert event.aggregate_id == "opp-1"
    assert event.workflow_id == "wi-1"
    assert event.payload.model_dump() == {
        "watch_intent_id": "wi-1",
        "event_id": "event-1",
        "market_type": "moneyline",
        "selection": "knicks",
        "best_sportsbook": "DraftKings",
        "best_price": 125,
        "matching_quotes": [
            {"sportsbook": "DraftKings", "price": 125},
            {"sportsbook": "FanDuel", "price": 125},
        ],
        "target_price": 120,
        "line": None,
    }


def test_build_watch_intent_triggered_event_records_the_terminal_transition() -> None:
    event = build_watch_intent_triggered_event(
        watch_intent_id="wi-1", opportunity=_opportunity()
    )

    assert event.event_type == "WatchIntentTriggered"
    assert event.aggregate_id == "wi-1"
    assert event.workflow_id == "wi-1"
    assert event.payload.model_dump() == {
        "watch_intent_id": "wi-1",
        "event_id": "event-1",
        "opportunity_id": "opp-1",
        "best_sportsbook": "DraftKings",
        "best_price": 125,
    }
