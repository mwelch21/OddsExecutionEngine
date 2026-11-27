from datetime import UTC, datetime

from backend.app.domain.models import (
    EventLifecycle,
    EventStatus,
    FillableQuotes,
    FillableSkipReason,
    LinePhase,
    Quote,
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _has_started(starts_at: datetime | None, now: datetime) -> bool:
    # No known start time has not started, matching every other read of it.
    return starts_at is not None and _aware(starts_at) <= _aware(now)


class EventStatusEngine:
    """Event status from what the provider offered, and what that lets a watch fill.

    The signal is feed presence, which costs nothing (#38). A started event the
    provider still offers is live; a started event it no longer offers has ended.
    The start time alone never makes an event live or ended.
    """

    def observe_offered(self, starts_at: datetime | None, now: datetime) -> EventStatus:
        """The provider offered the event in this pull."""
        return EventStatus.LIVE if _has_started(starts_at, now) else EventStatus.UPCOMING

    def observe_absent_from_sport_pull(
        self, starts_at: datetime | None, now: datetime
    ) -> EventStatus | None:
        """A stored event the sport-wide pull did not offer. None leaves it as stored.

        Absence before kickoff proves nothing, so only a started event ends.
        """
        return EventStatus.ENDED if _has_started(starts_at, now) else None

    def observe_event_refresh(
        self, *, offered: bool, starts_at: datetime | None, now: datetime
    ) -> EventStatus:
        """A per-event refresh: a 404 or empty answer reads as ended."""
        return self.observe_offered(starts_at, now) if offered else EventStatus.ENDED

    def line_phase(self, status: EventStatus) -> LinePhase:
        """The phase of a line pulled while the event had this status."""
        return LinePhase.LIVE if status is EventStatus.LIVE else LinePhase.PRE_GAME

    def fillable_quotes(
        self, lifecycle: EventLifecycle | None, quotes: list[Quote], now: datetime
    ) -> FillableQuotes:
        """The quotes a watch on this event may fill on.

        Ended: none. Live: live lines only, because a pre-game row a book left
        behind at kickoff is a price nobody can take any more. Upcoming but past
        its start: none, because nothing has observed it since kickoff. Upcoming,
        or an event never stored: every quote.
        """
        if lifecycle is None:
            return FillableQuotes(quotes=quotes)
        status = lifecycle.status
        if status is EventStatus.ENDED:
            return FillableQuotes(quotes=[], skipped_reason=FillableSkipReason.EVENT_ENDED)
        if status is EventStatus.UPCOMING and _has_started(lifecycle.starts_at, now):
            return FillableQuotes(
                quotes=[], skipped_reason=FillableSkipReason.EVENT_STATUS_UNOBSERVED
            )
        if status is EventStatus.LIVE:
            return FillableQuotes(
                quotes=[quote for quote in quotes if quote.phase is LinePhase.LIVE]
            )
        return FillableQuotes(quotes=quotes)
