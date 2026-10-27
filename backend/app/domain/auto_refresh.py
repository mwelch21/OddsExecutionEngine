"""Auto-Refresh: the operator's switch for refreshing while they are away (ADR-016).

It is the only automatic path to the provider. A worker polls, finds the sports
that have a watch the evaluator will act on, and refreshes each one whose
cooldown has elapsed. Nothing here spends credits on its own: the settings say
whether and how often, the cadence engine says which sports are due.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from backend.app.domain.base import DomainModel

DEFAULT_INTERVAL_MINUTES = 5
MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 60


class AutoRefreshSettings(DomainModel):
    """The operator's choice, exactly as last set; survives restarts.

    `quota_floor` of None means "derive it": 10% of the plan, once quota
    observations exist to derive it from.
    """

    enabled: bool = False
    interval_minutes: int = Field(
        default=DEFAULT_INTERVAL_MINUTES,
        ge=MIN_INTERVAL_MINUTES,
        le=MAX_INTERVAL_MINUTES,
    )
    quota_floor: int | None = Field(default=None, ge=0)


class RefreshOutcomeStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AutoRefreshOutcome(DomainModel):
    """What the worker's most recent refresh did; a failure never stops the next poll."""

    sport: str
    status: RefreshOutcomeStatus
    at: datetime
    events_refreshed: int = 0
    error: str | None = None


class AutoRefreshStatus(DomainModel):
    settings: AutoRefreshSettings
    last_outcome: AutoRefreshOutcome | None = None


class AutoRefreshCycleReport(DomainModel):
    """One poll. `ran` is False when another worker held the cycle lock."""

    ran: bool
    enabled: bool = False
    candidate_sports: list[str] = []
    refreshed: list[AutoRefreshOutcome] = []
