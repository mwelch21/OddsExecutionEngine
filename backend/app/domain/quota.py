"""Upstream credit quota: what each call reported, and what we believe is left (ADR-016).

The Odds API reports remaining and used credits in headers on every call. A
reading is what one call handed back; an observation is what we record from it,
falling back to a local `markets x regions` count when the headers are absent.
Each observation also says what kind of call it was, for which sport or event, and
what that one call spent: credit burn is counted per call, never per refresh.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from backend.app.domain.base import DomainModel


class QuotaSource(StrEnum):
    HEADERS = "headers"
    LOCAL = "local"


class UpstreamCallKind(StrEnum):
    """What an upstream call fetched. A balance check has no refresh behind it."""

    SPORT = "sport"
    EVENT = "event"
    BALANCE_CHECK = "balance_check"


class QuotaReading(DomainModel):
    """One upstream call's quota, exactly as the provider reported it.

    Header fields are None when the response did not carry them. `estimated_cost`
    is the local `markets x regions` count, used only when the headers are absent.
    `credits_spent` is this call's own cost header (`x-requests-last`).
    `out_of_credits` is the provider's OUT_OF_USAGE_CREDITS answer.
    """

    kind: UpstreamCallKind | None = None
    sport_key: str | None = None
    event_id: str | None = None
    credits_remaining: int | None = None
    credits_used: int | None = None
    credits_spent: int | None = Field(default=None, ge=0)
    estimated_cost: int = Field(ge=0)
    out_of_credits: bool = False
    observed_at: datetime


class QuotaObservation(DomainModel):
    """What we record per upstream call. `remaining`/`used` are None until known.

    `kind` and `credits_spent` are None only on rows recorded before they were kept.
    """

    remaining: int | None
    used: int | None
    source: QuotaSource
    out_of_credits: bool = False
    observed_at: datetime
    kind: UpstreamCallKind | None = None
    sport_key: str | None = None
    event_id: str | None = None
    credits_spent: int | None = None


class QuotaStatus(DomainModel):
    """The latest observation and what it means for the operator."""

    latest: QuotaObservation | None
    floor: int | None
    paused: bool
    out_of_credits: bool = False


class OutOfUsageCreditsError(Exception):
    """The provider refused a call: this month's credits are spent."""

    def __init__(self) -> None:
        super().__init__("Upstream credits are exhausted for the month (OUT_OF_USAGE_CREDITS).")


# A failed call still has its observation. The refresh that made it links to it, and
# the error is the only thing that leaves the provider, so the id rides on it.
_OBSERVATION_ATTRIBUTE = "quota_observation_id"


def link_observation(error: BaseException, observation_id: int | None) -> None:
    """Mark `error` as raised after the call recorded as `observation_id`.

    The first link wins: it names the call that actually failed.
    """
    if observation_id is not None and linked_observation(error) is None:
        setattr(error, _OBSERVATION_ATTRIBUTE, observation_id)


def linked_observation(error: BaseException) -> int | None:
    value = getattr(error, _OBSERVATION_ATTRIBUTE, None)
    return value if isinstance(value, int) else None
