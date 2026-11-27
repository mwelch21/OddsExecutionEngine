from datetime import datetime

from backend.app.domain.models import (
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
        self, intent: WatchIntent, status: EventStatus | None, now: datetime
    ) -> ExpiredReason | None:
        """Why an active watch must expire now, or None if it stays armed.

        A passed TTL is checked first: its time is known exactly, while a status
        change is only seen when a refresh observes it. An event never stored
        has no status, so only the TTL applies.
        """
        if intent.status is not WatchStatus.ACTIVE:
            return None
        if intent.is_expired_at(now):
            return ExpiredReason.TTL
        if status is None:
            return None
        return self.lifecycle_expiry(intent.window, status)

    def expiry_reasons(
        self,
        intents: list[WatchIntent],
        status_by_event: dict[str, EventStatus],
        now: datetime,
    ) -> dict[str, ExpiredReason]:
        """The watches that must expire now, by id, with the reason for each."""
        reasons: dict[str, ExpiredReason] = {}
        for intent in intents:
            reason = self.expiry_reason(intent, status_by_event.get(intent.event_id), now)
            if reason is not None:
                reasons[intent.id] = reason
        return reasons
