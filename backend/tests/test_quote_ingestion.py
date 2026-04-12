import pytest

from backend.app.application.quote_ingestion_service import QuoteIngestionService
from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import (
    MarketType,
    PersistedQuote,
    Quote,
    QuoteRefreshPersistenceResult,
)
from backend.app.engines.normalization_engine import NormalizationEngine
from backend.app.infrastructure.publishers.in_memory_publisher import (
    InMemoryWorkflowEventPublisher,
)


class RecordingQuoteIngestionProvider:
    def __init__(self, quotes: list[Quote]) -> None:
        self._quotes = quotes

    def list_quotes(self, event_id: str) -> list[Quote]:
        return list(self._quotes)


class RecordingQuoteIngestionUnitOfWork:
    def __init__(
        self,
        *,
        persistence_result: QuoteRefreshPersistenceResult,
        fail_on_persist: bool = False,
    ) -> None:
        self._persistence_result = persistence_result
        self._fail_on_persist = fail_on_persist
        self._staged_events: list[WorkflowEvent] = []
        self._committed_events: tuple[WorkflowEvent, ...] = ()

    def __enter__(self) -> "RecordingQuoteIngestionUnitOfWork":
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

    def persist_quotes(
        self,
        event_id: str,
        quotes: list[Quote],
    ) -> QuoteRefreshPersistenceResult:
        if self._fail_on_persist:
            raise RuntimeError("quote persistence failed")
        return self._persistence_result

    def stage_event(self, event: WorkflowEvent) -> None:
        self._staged_events.append(event)

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]:
        return self._committed_events


def test_quote_ingestion_service_publishes_events_after_commit() -> None:
    quote = Quote(
        event_id="event-1",
        sportsbook="BookA",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        price=120,
    )
    persistence_result = QuoteRefreshPersistenceResult(
        event_id="event-1",
        persisted_quotes=[
            PersistedQuote(
                quote=quote,
                market_id="market-1",
                market_created=True,
            )
        ],
        created_market_count=1,
        updated_latest_count=1,
        appended_history_count=1,
    )
    unit_of_work = RecordingQuoteIngestionUnitOfWork(
        persistence_result=persistence_result,
    )
    publisher = InMemoryWorkflowEventPublisher()
    service = QuoteIngestionService(
        unit_of_work_factory=lambda: unit_of_work,
        quote_provider=RecordingQuoteIngestionProvider([quote]),
        normalization_engine=NormalizationEngine(),
        workflow_event_publisher=publisher,
    )

    summary = service.refresh_quotes("event-1")

    assert summary.event_id == "event-1"
    assert summary.ingested_quote_count == 1
    assert summary.created_market_count == 1
    assert summary.updated_latest_count == 1
    assert summary.appended_history_count == 1
    assert summary.emitted_event_types == [
        "MarketSnapshotCreated",
        "QuoteUpdated",
        "QuotesRefreshed",
    ]
    assert [event.event_type for event in publisher.published_events] == summary.emitted_event_types


def test_quote_ingestion_service_does_not_publish_events_on_rollback() -> None:
    quote = Quote(
        event_id="event-1",
        sportsbook="BookA",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        price=120,
    )
    persistence_result = QuoteRefreshPersistenceResult(
        event_id="event-1",
        persisted_quotes=[],
        created_market_count=0,
        updated_latest_count=0,
        appended_history_count=0,
    )
    unit_of_work = RecordingQuoteIngestionUnitOfWork(
        persistence_result=persistence_result,
        fail_on_persist=True,
    )
    publisher = InMemoryWorkflowEventPublisher()
    service = QuoteIngestionService(
        unit_of_work_factory=lambda: unit_of_work,
        quote_provider=RecordingQuoteIngestionProvider([quote]),
        normalization_engine=NormalizationEngine(),
        workflow_event_publisher=publisher,
    )

    with pytest.raises(RuntimeError, match="quote persistence failed"):
        service.refresh_quotes("event-1")

    assert publisher.published_events == []
    assert unit_of_work.committed_events == ()
