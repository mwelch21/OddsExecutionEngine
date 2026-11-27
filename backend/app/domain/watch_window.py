"""The watch window a new watch gets (ADR-017).

`WatchWindowPolicy` is the only place the default window lives. A future
operator or user preference changes the policy's input, never the watch model
or the watches already stored.
"""

from enum import StrEnum

from backend.app.domain.models import EventLifecycle, EventStatus, WatchWindow


class WatchWindowRefusal(StrEnum):
    """Why a watch cannot be created with the window asked for."""

    # Nothing on an ended event can fill, so a watch on it could never fire.
    EVENT_ENDED = "EVENT_ENDED"
    # A pre-game watch on a live event would expire the moment it was made.
    WINDOW_CLOSED = "WINDOW_CLOSED"


class WatchWindowNotAllowedError(Exception):
    """Raised when a watch cannot be created on this event with this window."""

    def __init__(self, refusal: WatchWindowRefusal, message: str) -> None:
        super().__init__(message)
        self.refusal = refusal


class WatchWindowPolicy:
    """Resolve the window of a watch at creation, from the event's status."""

    def default_for(self, status: EventStatus) -> WatchWindow:
        """The window a watch gets when its author names none.

        Upcoming gives `pre_game`, live gives `live`. An event never stored, or
        stored upcoming but not observed since kickoff, reads as upcoming.
        """
        return WatchWindow.LIVE if status is EventStatus.LIVE else WatchWindow.PRE_GAME

    def resolve(
        self, requested: WatchWindow | None, lifecycle: EventLifecycle | None
    ) -> WatchWindow:
        """The window to store, or WatchWindowNotAllowedError when none can apply."""
        status = lifecycle.status if lifecycle is not None else EventStatus.UPCOMING
        if status is EventStatus.ENDED:
            raise WatchWindowNotAllowedError(
                WatchWindowRefusal.EVENT_ENDED,
                "The event has ended, so a watch on it can never fill.",
            )
        if requested is None:
            return self.default_for(status)
        if requested is WatchWindow.PRE_GAME and status is EventStatus.LIVE:
            raise WatchWindowNotAllowedError(
                WatchWindowRefusal.WINDOW_CLOSED,
                "The event is live, so a pre_game watch would expire at once. "
                "Use live or full_game.",
            )
        return requested
