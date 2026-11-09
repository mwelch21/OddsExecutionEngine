"""Where credits go: the balance over time and the burn per month (#104).

Both are read from quota observations, one per upstream call. A refresh is not a
call: refreshes coalesced onto one call are billed, and counted, once.
"""

from datetime import datetime

from pydantic import Field

from backend.app.domain.base import DomainModel
from backend.app.domain.quota import UpstreamCallKind

# Hourly buckets over at most 30 days: 720 points at most.
MAX_HISTORY_DAYS = 30


class RemainingReading(DomainModel):
    """One observation's balance, as the history reads it."""

    observed_at: datetime
    remaining: int


class QuotaHistoryPoint(DomainModel):
    """The last remaining balance observed in one UTC hour."""

    hour: datetime
    remaining: int


class BurnRow(DomainModel):
    """Calls and credits for one (sport, kind) pair, as summed in storage."""

    sport_key: str | None
    kind: UpstreamCallKind
    credits: int = Field(ge=0)
    calls: int = Field(ge=0)


class SportBurn(DomainModel):
    sport_key: str
    credits: int
    calls: int


class KindBurn(DomainModel):
    kind: UpstreamCallKind
    credits: int
    calls: int


class CreditBurn(DomainModel):
    """One calendar month (UTC) of spend, per sport and per call kind.

    Balance checks name no sport, so they appear under kind only. Calls recorded
    before their kind was kept are not counted.
    """

    month: str
    starts_at: datetime
    ends_at: datetime
    total_credits: int
    total_calls: int
    by_sport: list[SportBurn]
    by_kind: list[KindBurn]
