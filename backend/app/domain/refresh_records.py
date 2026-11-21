"""The refresh log: what each refresh did (#96).

A refresh is one deliberate pull for a sport or an event, manual or Auto-Refresh. It
is not an upstream call: refreshes made at the same moment can share one call, and a
balance check is a call with no refresh behind it. Every refresh leaves one record,
whatever its outcome. Records are admin read data only; no event is emitted.
"""

import re
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum

from pydantic import Field

from backend.app.domain.base import DomainModel
from backend.app.domain.quota import OutOfUsageCreditsError

# An upstream HTTP error's text carries the request URL, and the provider's key
# rides in its query string. The log is read back over the API, so it never keeps it.
_SECRET_QUERY_PARAM = re.compile(r"(api_?key=)[^&\s'\"]+", re.IGNORECASE)


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


class RefreshErrorCode(StrEnum):
    """Why a refresh did not succeed: a closed set, part of the public API.

    The error text carries the detail; the code is what a reader filters on.
    """

    UPSTREAM_HTTP = "UPSTREAM_HTTP"  # the provider answered with an HTTP error
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"  # the provider timed out or could not be reached
    OUT_OF_USAGE_CREDITS = "OUT_OF_USAGE_CREDITS"  # refused; same code as the 503
    INVALID_RESPONSE = "INVALID_RESPONSE"  # the provider answered, but not usably
    INTERNAL = "INTERNAL"  # anything else


# Maps a refresh's exception to its code. The provider adapter supplies the one
# that knows its transport's errors; see `classify_domain_error` for the base.
RefreshErrorClassifier = Callable[[Exception], RefreshErrorCode]


def classify_domain_error(error: Exception) -> RefreshErrorCode:
    """The codes the domain alone can tell; everything else is INTERNAL."""
    if isinstance(error, OutOfUsageCreditsError):
        return RefreshErrorCode.OUT_OF_USAGE_CREDITS
    return RefreshErrorCode.INTERNAL


class RefreshResult(DomainModel):
    """How a refresh ended: the outcome, its code and the operator-safe text."""

    outcome: RefreshOutcomeStatus
    error_code: RefreshErrorCode | None = None
    error: str | None = None

    @classmethod
    def from_error(
        cls, error: Exception | None, classify: RefreshErrorClassifier = classify_domain_error
    ) -> "RefreshResult":
        if error is None:
            return cls(outcome=RefreshOutcomeStatus.SUCCEEDED)
        code = classify(error)
        return cls(
            outcome=RefreshOutcomeStatus.REFUSED
            if code is RefreshErrorCode.OUT_OF_USAGE_CREDITS
            else RefreshOutcomeStatus.FAILED,
            error_code=code,
            error=_SECRET_QUERY_PARAM.sub(r"\1[redacted]", str(error) or type(error).__name__),
        )


class RefreshRecord(DomainModel):
    """One refresh. `event_id` is None for a sport-wide refresh.

    `quota_observation_id` links the upstream call the refresh used (#104): None if
    it failed before any call, shared by refreshes coalesced onto one call.
    `credits_spent` is that call's cost, read back through the link and never
    written: the call is billed once however many refreshes share it.
    """

    scope: RefreshScope
    sport_key: str
    event_id: str | None = None
    trigger: RefreshTrigger
    started_at: datetime
    finished_at: datetime
    outcome: RefreshOutcomeStatus
    error_code: RefreshErrorCode | None = None
    error: str | None = None
    events_refreshed: int = Field(default=0, ge=0)
    quota_observation_id: int | None = None
    credits_spent: int | None = None


class RefreshRecordFilter(DomainModel):
    sport_key: str | None = None
    trigger: RefreshTrigger | None = None
    outcome: RefreshOutcomeStatus | None = None
    error_code: RefreshErrorCode | None = None


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
