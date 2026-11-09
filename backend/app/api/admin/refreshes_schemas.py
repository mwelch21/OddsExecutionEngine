from datetime import datetime

from pydantic import BaseModel

from backend.app.domain.refresh_records import (
    RefreshErrorCode,
    RefreshOutcomeStatus,
    RefreshRecord,
    RefreshRecordPage,
    RefreshScope,
    RefreshTrigger,
)


class RefreshRecordResponse(BaseModel):
    """One refresh. `event_id` is null for a sport-wide refresh."""

    scope: RefreshScope
    sport: str
    event_id: str | None
    trigger: RefreshTrigger
    started_at: datetime
    finished_at: datetime
    outcome: RefreshOutcomeStatus
    error_code: RefreshErrorCode | None
    error: str | None
    events_refreshed: int
    # What the upstream call it used spent. Null when it made no call, or the call's
    # cost was never recorded. Coalesced refreshes each show their shared call's cost.
    credits_spent: int | None

    @classmethod
    def from_domain(cls, record: RefreshRecord) -> "RefreshRecordResponse":
        return cls(
            scope=record.scope,
            sport=record.sport_key,
            event_id=record.event_id,
            trigger=record.trigger,
            started_at=record.started_at,
            finished_at=record.finished_at,
            outcome=record.outcome,
            error_code=record.error_code,
            error=record.error,
            events_refreshed=record.events_refreshed,
            credits_spent=record.credits_spent,
        )


class RefreshListResponse(BaseModel):
    refreshes: list[RefreshRecordResponse]
    page: int
    page_size: int
    total_items: int
    total_pages: int

    @classmethod
    def from_domain(cls, page: RefreshRecordPage) -> "RefreshListResponse":
        return cls(
            refreshes=[RefreshRecordResponse.from_domain(record) for record in page.records],
            page=page.page,
            page_size=page.page_size,
            total_items=page.total_items,
            total_pages=page.total_pages,
        )
