from datetime import datetime

from pydantic import BaseModel, Field

from backend.app.domain.auto_refresh import (
    MAX_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    AutoRefreshSettings,
    AutoRefreshStatus,
    RefreshOutcomeStatus,
)
from backend.app.domain.quota import QuotaSource


class AutoRefreshSettingsRequest(BaseModel):
    """A full replacement of the settings; an omitted `quota_floor` means "derive it"."""

    enabled: bool
    interval_minutes: int = Field(ge=MIN_INTERVAL_MINUTES, le=MAX_INTERVAL_MINUTES)
    quota_floor: int | None = Field(default=None, ge=0)

    def to_domain(self) -> AutoRefreshSettings:
        return AutoRefreshSettings(
            enabled=self.enabled,
            interval_minutes=self.interval_minutes,
            quota_floor=self.quota_floor,
        )


class AutoRefreshOutcomeResponse(BaseModel):
    sport: str
    status: RefreshOutcomeStatus
    at: datetime
    events_refreshed: int
    error: str | None


class QuotaResponse(BaseModel):
    """The latest observed balance. `floor` is the one in force: the operator's
    `quota_floor`, or 10% of the plan when that is unset."""

    remaining: int | None
    used: int | None
    floor: int | None
    source: QuotaSource
    observed_at: datetime


class AutoRefreshResponse(BaseModel):
    enabled: bool
    interval_minutes: int
    quota_floor: int | None
    last_outcome: AutoRefreshOutcomeResponse | None
    # Out of credits: still on, but nothing paid is pulled until credits return.
    paused: bool
    quota: QuotaResponse | None

    @classmethod
    def from_domain(cls, status: AutoRefreshStatus) -> "AutoRefreshResponse":
        outcome = status.last_outcome
        quota = status.quota
        latest = quota.latest if quota else None
        return cls(
            enabled=status.settings.enabled,
            interval_minutes=status.settings.interval_minutes,
            quota_floor=status.settings.quota_floor,
            last_outcome=None
            if outcome is None
            else AutoRefreshOutcomeResponse(
                sport=outcome.sport,
                status=outcome.status,
                at=outcome.at,
                events_refreshed=outcome.events_refreshed,
                error=outcome.error,
            ),
            paused=quota.paused if quota else False,
            quota=None
            if quota is None or latest is None
            else QuotaResponse(
                remaining=latest.remaining,
                used=latest.used,
                floor=quota.floor,
                source=latest.source,
                observed_at=latest.observed_at,
            ),
        )
