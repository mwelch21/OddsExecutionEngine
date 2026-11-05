"""Upstream credit quota: what each call reported, and what we believe is left (ADR-016).

The Odds API reports remaining and used credits in headers on every call. A
reading is what one call handed back; an observation is what we record from it,
falling back to a local `markets x regions` count when the headers are absent.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from backend.app.domain.base import DomainModel


class QuotaSource(StrEnum):
    HEADERS = "headers"
    LOCAL = "local"


class QuotaReading(DomainModel):
    """One upstream call's quota, exactly as the provider reported it.

    Header fields are None when the response did not carry them. `estimated_cost`
    is the local `markets x regions` count, used only when the headers are absent.
    `out_of_credits` is the provider's OUT_OF_USAGE_CREDITS answer.
    """

    credits_remaining: int | None = None
    credits_used: int | None = None
    estimated_cost: int = Field(ge=0)
    out_of_credits: bool = False
    observed_at: datetime


class QuotaObservation(DomainModel):
    """What we record per upstream call. `remaining`/`used` are None until known."""

    remaining: int | None
    used: int | None
    source: QuotaSource
    out_of_credits: bool = False
    observed_at: datetime


class QuotaStatus(DomainModel):
    """The latest observation and what it means for the operator."""

    latest: QuotaObservation | None
    floor: int | None
    paused: bool


class OutOfUsageCreditsError(Exception):
    """The provider refused a call: this month's credits are spent."""

    def __init__(self) -> None:
        super().__init__("Upstream credits are exhausted for the month (OUT_OF_USAGE_CREDITS).")
