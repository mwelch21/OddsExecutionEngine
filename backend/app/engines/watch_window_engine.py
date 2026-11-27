from datetime import UTC, datetime

from backend.app.domain.models import (
    EventLifecycle,
    EventStatus,
    ExpiredReason,
    LinePhase,
    WatchIntent,
    WatchStatus,
    WatchWindow,
)


class WatchWindowEngine:
    """What a watch's window lets it fill on, and when the window closes (ADR-017).

    Works with `EventStatusEngine`: that engine says which of an event's lines
    can fill at all; this one says which of those a given watch may use.
    """

    def admits(self, window: WatchWindow, phase: LinePhase | None) -> bool:
        """True when a line of this phase may fill a watch with this window.

        A line with no phase is pre-game, as storage treats it.
        """
        if window is WatchWindow.FULL_GAME:
            return True
        line_phase = phase or LinePhase.PRE_GAME
        if window is WatchWindow.LIVE:
            return line_phase is LinePhase.LIVE
        return line_phase is LinePhase.PRE_GAME

    def lifecycle_expiry(
        self, window: WatchWindow, status: EventStatus
    ) -> ExpiredReason | None:
        """Why the event's status closes this window, or None while it is open.

        Ended closes every window. Live closes only `pre_game`.
        """
        if status is EventStatus.ENDED:
            return ExpiredReason.EVENT_ENDED
        if status is EventStatus.LIVE and window is WatchWindow.PRE_GAME:
            return ExpiredReason.EVENT_STARTED
        return None

    def expiry_reason(
        self, intent: WatchIntent, lifecycle: EventLifecycle | None, now: datetime
    ) -> ExpiredReason | None:
        """Why an active watch must expire now, or None if it stays armed.

        A passed TTL is checked first: its time is known exactly, while a status
        change is only seen when a refresh observes it. An event never stored
        has no lifecycle, so only the TTL applies.

        A `pre_game` watch also closes once the stored start time has passed,
        even while the event is still stored `upcoming`: nothing observed it
        since kickoff, and its pre-game lines cannot fill any more. Without this,
        an event never refreshed after its start keeps the watch armed forever
        (ADR-017). The event's stored status is left as it is (ADR-019).
        """
        if intent.status is not WatchStatus.ACTIVE:
            return None
        if intent.is_expired_at(now):
            return ExpiredReason.TTL
        if lifecycle is None:
            return None
        reason = self.lifecycle_expiry(intent.window, lifecycle.status)
        if reason is None and intent.window is WatchWindow.PRE_GAME:
            if _has_started(lifecycle.starts_at, now):
                return ExpiredReason.EVENT_STARTED
        return reason

    def expiry_reasons(
        self,
        intents: list[WatchIntent],
        lifecycle_by_event: dict[str, EventLifecycle],
        now: datetime,
    ) -> dict[str, ExpiredReason]:
        """The watches that must expire now, by id, with the reason for each."""
        reasons: dict[str, ExpiredReason] = {}
        for intent in intents:
            reason = self.expiry_reason(intent, lifecycle_by_event.get(intent.event_id), now)
            if reason is not None:
                reasons[intent.id] = reason
        return reasons


def _has_started(starts_at: datetime | None, now: datetime) -> bool:
    if starts_at is None:
        return False
    aware = starts_at if starts_at.tzinfo is not None else starts_at.replace(tzinfo=UTC)
    return aware <= now
