"""Auto-Refresh: the operator's switch for refreshing while they are away (ADR-016).

It is the only automatic path to the provider. A worker polls, finds the sports
that have a watch the evaluator will act on, and refreshes each one whose
cooldown has elapsed. Nothing here spends credits on its own: the settings say
whether and how often, the candidate engine says which sports a watch can use,
and the cadence engine says which of those are due.

A sport with a candidate watch on a live event runs on the live interval, every
other candidate sport on the upcoming one (#128). Both are set by the operator;
nothing changes an interval by itself.
"""

from datetime import datetime

from pydantic import Field

from backend.app.domain.base import DomainModel
from backend.app.domain.models import EventStatus, WatchWindow
from backend.app.domain.quota import QuotaStatus
from backend.app.domain.refresh_records import RefreshOutcomeStatus

DEFAULT_INTERVAL_MINUTES = 5
MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 60


class AutoRefreshSettings(DomainModel):
    """The operator's choice, exactly as last set; survives restarts.

    `interval_minutes` is the upcoming interval: the cooldown of a sport whose
    candidate watches are all on upcoming events. `live_interval_minutes` is the
    cooldown of a sport with a candidate watch on a live event. One live
    interval covers every live game.

    `quota_floor` of None means "derive it": 10% of the plan, once quota
    observations exist to derive it from.
    """

    enabled: bool = False
    interval_minutes: int = Field(
        default=DEFAULT_INTERVAL_MINUTES,
        ge=MIN_INTERVAL_MINUTES,
        le=MAX_INTERVAL_MINUTES,
    )
    live_interval_minutes: int = Field(
        default=DEFAULT_INTERVAL_MINUTES,
        ge=MIN_INTERVAL_MINUTES,
        le=MAX_INTERVAL_MINUTES,
    )
    quota_floor: int | None = Field(default=None, ge=0)


class WatchedEvent(DomainModel):
    """One active watch as the candidate rule sees it: its window, and the
    sport and status of its event. Only watches on an event with a stored
    sport appear, because only those can be refreshed sport-wide.
    """

    sport: str
    league: str | None = None
    status: EventStatus
    window: WatchWindow
    starts_at: datetime | None = None


class CandidateSport(DomainModel):
    """A stored (sport, league) that some watch can use a refresh of now.

    `live` is True when at least one of those watches is on a live event, so
    the sport runs on the live interval.
    """

    sport: str
    league: str | None = None
    live: bool = False


class AutoRefreshOutcome(DomainModel):
    """What one of the worker's refreshes did; a failure never stops the next poll.

    The status endpoint's `last_outcome` is the newest Auto-Refresh refresh record,
    read back in this shape.
    """

    sport: str
    status: RefreshOutcomeStatus
    at: datetime
    events_refreshed: int = 0
    error: str | None = None


class AutoRefreshStatus(DomainModel):
    settings: AutoRefreshSettings
    last_outcome: AutoRefreshOutcome | None = None
    quota: QuotaStatus | None = None


class AutoRefreshCycleReport(DomainModel):
    """One poll. `ran` is False when another worker held the cycle lock.

    `paused` is True when credits are exhausted: the switch stays on, but nothing
    paid is pulled until a balance check shows credits again.
    """

    ran: bool
    enabled: bool = False
    paused: bool = False
    candidate_sports: list[str] = []
    # The candidate sports on the live interval; a subset of `candidate_sports`.
    live_sports: list[str] = []
    refreshed: list[AutoRefreshOutcome] = []
