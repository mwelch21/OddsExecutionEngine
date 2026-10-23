import pytest

from backend.app.application.quote_ingestion_service import (
    QuoteIngestionService,
    UnknownEventError,
    UnresolvableEventSportError,
)
from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import (
    EventInfo,
    EventSport,
    MarketType,
    PersistedQuote,
    ProviderFetchReport,
    Quote,
    QuoteRefreshPersistenceResult,
    SupportedSport,
)
from backend.app.engines.normalization_engine import NormalizationEngine
from backend.app.infrastructure.publishers.in_memory_publisher import (
    InMemoryWorkflowEventPublisher,
)

NBA = EventSport(sport="basketball", league="NBA")


class RecordingQuoteIngestionProvider:
    def __init__(self, quotes: list[Quote], known_event: EventInfo | None = None) -> None:
        self._quotes = quotes
        self._known_event = known_event
        self.list_quotes_calls: list[tuple[str, str]] = []

    def list_quotes(self, event_id: str, sport: str) -> list[Quote]:
        self.list_quotes_calls.append((event_id, sport))
        return list(self._quotes)

    def list_quotes_for_sport(
        self, sport: str
    ) -> tuple[dict[str, list[Quote]], ProviderFetchReport]:
        return {}, ProviderFetchReport(upstream_contacted=True, data_age_seconds=0.0)

    def get_event_info(self, event_id: str) -> EventInfo | None:
        return self._known_event

    def list_supported_sports(self) -> list[SupportedSport]:
        return [
            SupportedSport(key="basketball_nba", sport="basketball", league="NBA"),
            SupportedSport(key="icehockey_nhl", sport="ice_hockey", league="NHL"),
        ]


class RecordingQuoteIngestionUnitOfWork:
    def __init__(
        self,
        *,
        persistence_result: QuoteRefreshPersistenceResult,
        fail_on_persist: bool = False,
        event_sport: EventSport | None = NBA,
    ) -> None:
        self._persistence_result = persistence_result
        self._event_sport = event_sport
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
        event_metadata: dict[str, object] | None = None,
    ) -> QuoteRefreshPersistenceResult:
        if self._fail_on_persist:
            raise RuntimeError("quote persistence failed")
        return self._persistence_result

    def get_event_sport(self, event_id: str) -> EventSport | None:
        return self._event_sport

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


def _empty_persistence_result() -> QuoteRefreshPersistenceResult:
    return QuoteRefreshPersistenceResult(
        event_id="event-1",
        persisted_quotes=[],
        created_market_count=0,
        updated_latest_count=0,
        appended_history_count=0,
    )


def _service(
    unit_of_work: RecordingQuoteIngestionUnitOfWork,
    provider: RecordingQuoteIngestionProvider,
) -> QuoteIngestionService:
    return QuoteIngestionService(
        unit_of_work_factory=lambda: unit_of_work,
        quote_provider=provider,
        normalization_engine=NormalizationEngine(),
        workflow_event_publisher=InMemoryWorkflowEventPublisher(),
    )


def test_per_event_refresh_makes_one_provider_call_for_the_events_own_sport() -> None:
    provider = RecordingQuoteIngestionProvider([])
    unit_of_work = RecordingQuoteIngestionUnitOfWork(
        persistence_result=_empty_persistence_result(),
        event_sport=EventSport(sport="ice_hockey", league="NHL"),
    )

    _service(unit_of_work, provider).refresh_quotes("event-1")

    assert provider.list_quotes_calls == [("event-1", "icehockey_nhl")]


def test_per_event_refresh_falls_back_to_what_the_provider_already_knows() -> None:
    provider = RecordingQuoteIngestionProvider(
        [], known_event=EventInfo(id="event-1", sport="basketball", league="NBA")
    )
    unit_of_work = RecordingQuoteIngestionUnitOfWork(
        persistence_result=_empty_persistence_result(),
        event_sport=None,
    )

    _service(unit_of_work, provider).refresh_quotes("event-1")

    assert provider.list_quotes_calls == [("event-1", "basketball_nba")]


def test_per_event_refresh_of_an_unknown_event_fails_without_calling_upstream() -> None:
    provider = RecordingQuoteIngestionProvider([])
    unit_of_work = RecordingQuoteIngestionUnitOfWork(
        persistence_result=_empty_persistence_result(),
        event_sport=None,
    )

    with pytest.raises(UnknownEventError):
        _service(unit_of_work, provider).refresh_quotes("event-1")

    assert provider.list_quotes_calls == []


@pytest.mark.parametrize(
    "event_sport",
    [
        EventSport(sport="curling", league="WCF"),
        EventSport(sport="basketball", league=None),
        EventSport(sport=None, league=None),
    ],
)
def test_per_event_refresh_never_scans_when_the_sport_cannot_be_resolved(
    event_sport: EventSport,
) -> None:
    provider = RecordingQuoteIngestionProvider([])
    unit_of_work = RecordingQuoteIngestionUnitOfWork(
        persistence_result=_empty_persistence_result(),
        event_sport=event_sport,
    )

    with pytest.raises(UnresolvableEventSportError):
        _service(unit_of_work, provider).refresh_quotes("event-1")

    assert provider.list_quotes_calls == []
