from datetime import datetime

from pydantic import BaseModel, Field

from backend.app.domain.auto_refresh import (
    DEFAULT_INTERVAL_MINUTES,
    MAX_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    AutoRefreshSettings,
    AutoRefreshStatus,
    RefreshOutcomeStatus,
)
from backend.app.domain.quota import QuotaSource


class AutoRefreshSettingsRequest(BaseModel):
    """A full replacement of the settings.

    An omitted `quota_floor` means "derive it"; an omitted `live_interval_minutes`
    means the default, 5; an omitted `sport_focus` means empty, no focus. A client
    that omits a field resets it, as any full replacement does.

    `sport_focus` holds catalog sport keys (`GET /api/v1/sports`); a key outside
    the catalog is a 422. Duplicates collapse and the stored order is sorted.
    """

    enabled: bool
    interval_minutes: int = Field(ge=MIN_INTERVAL_MINUTES, le=MAX_INTERVAL_MINUTES)
    live_interval_minutes: int = Field(
        default=DEFAULT_INTERVAL_MINUTES, ge=MIN_INTERVAL_MINUTES, le=MAX_INTERVAL_MINUTES
    )
    quota_floor: int | None = Field(default=None, ge=0)
    sport_focus: list[str] = Field(default_factory=list)

    def to_domain(self) -> AutoRefreshSettings:
        return AutoRefreshSettings(
            enabled=self.enabled,
            interval_minutes=self.interval_minutes,
            live_interval_minutes=self.live_interval_minutes,
            quota_floor=self.quota_floor,
            sport_focus=tuple(self.sport_focus),
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
    # The upcoming interval: sports whose candidate watches are all pre-game.
    interval_minutes: int
    # Sports with a candidate watch on a live event (#128).
    live_interval_minutes: int
    quota_floor: int | None
    # Catalog sport keys Auto-Refresh is narrowed to, sorted; empty = no focus (#132).
    sport_focus: list[str]
    # Catalog keys with a qualifying watch now, before the focus; read from stored
    # watches, never the provider.
    watched_sports: list[str]
    # Of those, the ones the focus drops: they have watches but are not refreshed.
    excluded_sports: list[str]
    last_outcome: AutoRefreshOutcomeResponse | None
    # Out of credits: still on, but nothing paid is pulled until credits return.
    paused: bool
    # No credits left: the newest call was refused, or reported 0 remaining.
    # False before any call.
    out_of_credits: bool
    quota: QuotaResponse | None

    @classmethod
    def from_domain(cls, status: AutoRefreshStatus) -> "AutoRefreshResponse":
        outcome = status.last_outcome
        quota = status.quota
        latest = quota.latest if quota else None
        return cls(
            enabled=status.settings.enabled,
            interval_minutes=status.settings.interval_minutes,
            live_interval_minutes=status.settings.live_interval_minutes,
            quota_floor=status.settings.quota_floor,
            sport_focus=list(status.settings.sport_focus),
            watched_sports=status.watched_sports,
            excluded_sports=status.excluded_sports,
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
            out_of_credits=quota.out_of_credits if quota else False,
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
