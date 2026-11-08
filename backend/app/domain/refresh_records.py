"""The refresh log: what each refresh did (#96).

A refresh is one deliberate pull for a sport or an event, manual or Auto-Refresh. It
is not an upstream call: refreshes made at the same moment can share one call, and a
balance check is a call with no refresh behind it. Every refresh leaves one record,
whatever its outcome. Records are admin read data only; no event is emitted.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from backend.app.domain.base import DomainModel

OUT_OF_USAGE_CREDITS = "OUT_OF_USAGE_CREDITS"


class RefreshScope(StrEnum):
    SPORT = "sport"
    EVENT = "event"


class RefreshTrigger(StrEnum):
    MANUAL = "manual"
    AUTO = "auto"


class RefreshOutcomeStatus(StrEnum):
    """`refused` is the provider declining the call (out of credits); anything else
    that stops a refresh part-way is `failed`."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUSED = "refused"


class RefreshRecord(DomainModel):
    """One refresh. `event_id` is None for a sport-wide refresh."""

    scope: RefreshScope
    sport_key: str
    event_id: str | None = None
    trigger: RefreshTrigger
    started_at: datetime
    finished_at: datetime
    outcome: RefreshOutcomeStatus
    error_code: str | None = None
    error: str | None = None
    events_refreshed: int = Field(default=0, ge=0)


class RefreshRecordFilter(DomainModel):
    sport_key: str | None = None
    trigger: RefreshTrigger | None = None
    outcome: RefreshOutcomeStatus | None = None


class RefreshRecordPage(DomainModel):
    """A page of refresh records, newest first, plus what "page 2 of 7" needs."""

    records: list[RefreshRecord]
    page: int
    page_size: int
    total_items: int

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return -(-self.total_items // self.page_size)
