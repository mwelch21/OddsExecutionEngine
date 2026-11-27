from datetime import datetime
from typing import Protocol

from backend.app.domain.events import WorkflowEvent, build_watch_intent_expired_event
from backend.app.domain.models import EventLifecycle, ExpiredReason, WatchIntent
from backend.app.engines.watch_window_engine import WatchWindowEngine


class WatchExpiryUnitOfWork(Protocol):
    """The part of a unit of work that watch expiry writes through."""

    def expire_watch_intents(self, reasons: dict[str, ExpiredReason]) -> list[WatchIntent]: ...

    def stage_event(self, event: WorkflowEvent) -> None: ...


class WatchExpirer:
    """Retires the watches that must expire now, in the caller's transaction.

    Shared by ingestion, which expires on the status write, and evaluation, which
    re-checks as a backstop (ADR-017), so both apply one rule the same way. Each
    expiry stages `WatchIntentExpired`; none stages a public event, so expiry
    never notifies.
    """

    def __init__(self, watch_window_engine: WatchWindowEngine | None = None) -> None:
        self._watch_window_engine = watch_window_engine or WatchWindowEngine()

    def expire(
        self,
        unit_of_work: WatchExpiryUnitOfWork,
        intents: list[WatchIntent],
        lifecycle_by_event: dict[str, EventLifecycle],
        now: datetime,
    ) -> list[WatchIntent]:
        """Expire each watch the engine closes; return the ones actually expired."""
        reasons = self._watch_window_engine.expiry_reasons(intents, lifecycle_by_event, now)
        retired = unit_of_work.expire_watch_intents(reasons)
        for intent in retired:
            unit_of_work.stage_event(
                build_watch_intent_expired_event(watch_intent_id=intent.id, intent=intent)
            )
        return retired
