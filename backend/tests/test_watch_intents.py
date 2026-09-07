from datetime import UTC, datetime, timedelta

import pytest

from backend.app.application.watch_intent_service import WatchIntentService
from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import (
    MarketType,
    WatchIntent,
    WatchIntentDraft,
    WatchStatus,
)
from backend.app.infrastructure.publishers.in_memory_publisher import (
    InMemoryWorkflowEventPublisher,
)


class RecordingWatchIntentUnitOfWork:
    def __init__(self, *, watches: list[WatchIntent] | None = None) -> None:
        self.watches: list[WatchIntent] = list(watches or [])
        self._staged_events: list[WorkflowEvent] = []
        self._committed_events: tuple[WorkflowEvent, ...] = ()

    def __enter__(self) -> "RecordingWatchIntentUnitOfWork":
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

    def create_watch_intent(self, watch_intent: WatchIntent) -> None:
        self.watches.append(watch_intent)

    def list_watch_intents(
        self,
        *,
        event_id: str | None = None,
        status: WatchStatus | None = None,
    ) -> list[WatchIntent]:
        return [
            watch
            for watch in self.watches
            if (event_id is None or watch.event_id == event_id)
            and (status is None or watch.status is status)
        ]

    def get_watch_intent(self, watch_intent_id: str) -> WatchIntent | None:
        return next((watch for watch in self.watches if watch.id == watch_intent_id), None)

    def update_watch_intent_status(self, watch_intent_id: str, status: WatchStatus) -> None:
        self.watches = [
            watch.model_copy(update={"status": status}) if watch.id == watch_intent_id else watch
            for watch in self.watches
        ]

    def stage_event(self, event: WorkflowEvent) -> None:
        self._staged_events.append(event)

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]:
        return self._committed_events


def _build_service(
    unit_of_work: RecordingWatchIntentUnitOfWork,
) -> tuple[WatchIntentService, InMemoryWorkflowEventPublisher]:
    publisher = InMemoryWorkflowEventPublisher()
    service = WatchIntentService(
        unit_of_work_factory=lambda: unit_of_work,
        workflow_event_publisher=publisher,
    )
    return service, publisher


def _build_watch(
    *,
    watch_id: str = "watch-1",
    status: WatchStatus = WatchStatus.ACTIVE,
    event_id: str = "event-1",
) -> WatchIntent:
    return WatchIntent(
        id=watch_id,
        event_id=event_id,
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
        status=status,
        created_at=datetime.now(UTC),
    )


def test_create_watch_persists_active_watch_and_publishes_submitted_event() -> None:
    unit_of_work = RecordingWatchIntentUnitOfWork()
    service, publisher = _build_service(unit_of_work)
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    watch = service.create_watch(
        WatchIntentDraft(
            event_id="event-1",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            target_price=120,
            expires_at=expires_at,
        )
    )

    assert watch.status is WatchStatus.ACTIVE
    assert watch.event_id == "event-1"
    assert watch.expires_at == expires_at
    assert watch.id
    assert unit_of_work.watches == [watch]
    assert [event.event_type for event in publisher.published_events] == ["WatchIntentSubmitted"]
    assert publisher.published_events[0].aggregate_id == watch.id


def test_create_watch_does_not_publish_when_transaction_fails() -> None:
    class FailingUnitOfWork(RecordingWatchIntentUnitOfWork):
        def create_watch_intent(self, watch_intent: WatchIntent) -> None:
            raise RuntimeError("watch persistence failed")

    unit_of_work = FailingUnitOfWork()
    service, publisher = _build_service(unit_of_work)

    with pytest.raises(RuntimeError, match="watch persistence failed"):
        service.create_watch(
            WatchIntentDraft(
                event_id="event-1",
                market_type=MarketType.MONEYLINE,
                selection="knicks",
                target_price=120,
            )
        )

    assert publisher.published_events == []


def test_list_watches_filters_by_event_and_status() -> None:
    unit_of_work = RecordingWatchIntentUnitOfWork(
        watches=[
            _build_watch(watch_id="watch-1", event_id="event-1"),
            _build_watch(watch_id="watch-2", event_id="event-2"),
            _build_watch(watch_id="watch-3", event_id="event-1", status=WatchStatus.CANCELLED),
        ]
    )
    service, _ = _build_service(unit_of_work)

    assert [watch.id for watch in service.list_watches()] == ["watch-1", "watch-2", "watch-3"]
    assert [watch.id for watch in service.list_watches(event_id="event-1")] == [
        "watch-1",
        "watch-3",
    ]
    assert [
        watch.id for watch in service.list_watches(event_id="event-1", status=WatchStatus.ACTIVE)
    ] == ["watch-1"]


def test_get_watch_returns_none_for_unknown_id() -> None:
    unit_of_work = RecordingWatchIntentUnitOfWork(watches=[_build_watch()])
    service, _ = _build_service(unit_of_work)

    assert service.get_watch("watch-1") is not None
    assert service.get_watch("missing") is None


def test_cancel_watch_sets_cancelled_status_and_publishes_event() -> None:
    unit_of_work = RecordingWatchIntentUnitOfWork(watches=[_build_watch()])
    service, publisher = _build_service(unit_of_work)

    cancelled = service.cancel_watch("watch-1")

    assert cancelled is not None
    assert cancelled.status is WatchStatus.CANCELLED
    assert unit_of_work.watches[0].status is WatchStatus.CANCELLED
    assert [event.event_type for event in publisher.published_events] == ["WatchIntentCancelled"]


def test_cancel_watch_is_idempotent_and_does_not_republish() -> None:
    unit_of_work = RecordingWatchIntentUnitOfWork(
        watches=[_build_watch(status=WatchStatus.CANCELLED)]
    )
    service, publisher = _build_service(unit_of_work)

    cancelled = service.cancel_watch("watch-1")

    assert cancelled is not None
    assert cancelled.status is WatchStatus.CANCELLED
    assert publisher.published_events == []


def test_cancel_watch_returns_none_for_unknown_id() -> None:
    unit_of_work = RecordingWatchIntentUnitOfWork()
    service, publisher = _build_service(unit_of_work)

    assert service.cancel_watch("missing") is None
    assert publisher.published_events == []


def _build_watch_expiring(expires_at: datetime, watch_id: str = "watch-ttl") -> WatchIntent:
    return WatchIntent(
        id=watch_id,
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
        expires_at=expires_at,
        status=WatchStatus.ACTIVE,
        created_at=datetime.now(UTC),
    )


def test_watch_past_its_expiry_reads_as_expired_before_evaluation_corrects_it() -> None:
    unit_of_work = RecordingWatchIntentUnitOfWork(
        watches=[_build_watch_expiring(datetime.now(UTC) - timedelta(minutes=1))]
    )
    service, _ = _build_service(unit_of_work)

    watch = service.get_watch("watch-ttl")

    assert watch is not None
    assert watch.status is WatchStatus.EXPIRED
    assert unit_of_work.watches[0].status is WatchStatus.ACTIVE


def test_watch_with_future_expiry_still_reads_as_active() -> None:
    unit_of_work = RecordingWatchIntentUnitOfWork(
        watches=[_build_watch_expiring(datetime.now(UTC) + timedelta(minutes=1))]
    )
    service, _ = _build_service(unit_of_work)

    watch = service.get_watch("watch-ttl")

    assert watch is not None
    assert watch.status is WatchStatus.ACTIVE


def test_active_filter_excludes_watches_past_their_expiry() -> None:
    unit_of_work = RecordingWatchIntentUnitOfWork(
        watches=[
            _build_watch(watch_id="live"),
            _build_watch_expiring(datetime.now(UTC) - timedelta(minutes=1), "dead"),
        ]
    )
    service, _ = _build_service(unit_of_work)

    assert [w.id for w in service.list_watches(status=WatchStatus.ACTIVE)] == ["live"]


def test_expired_filter_includes_watches_past_their_expiry() -> None:
    unit_of_work = RecordingWatchIntentUnitOfWork(
        watches=[
            _build_watch(watch_id="live"),
            _build_watch_expiring(datetime.now(UTC) - timedelta(minutes=1), "dead"),
        ]
    )
    service, _ = _build_service(unit_of_work)

    expired = service.list_watches(status=WatchStatus.EXPIRED)

    assert [w.id for w in expired] == ["dead"]
    assert expired[0].status is WatchStatus.EXPIRED


def test_unfiltered_list_reports_effective_status_without_dropping_rows() -> None:
    unit_of_work = RecordingWatchIntentUnitOfWork(
        watches=[
            _build_watch(watch_id="live"),
            _build_watch_expiring(datetime.now(UTC) - timedelta(minutes=1), "dead"),
        ]
    )
    service, _ = _build_service(unit_of_work)

    listed = {w.id: w.status for w in service.list_watches()}

    assert listed == {"live": WatchStatus.ACTIVE, "dead": WatchStatus.EXPIRED}
