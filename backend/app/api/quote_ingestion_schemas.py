from pydantic import BaseModel, Field

from backend.app.domain.models import (
    QuoteRefreshSummary,
    SportRefreshResult,
    SupportedSport,
)


class QuoteRefreshRequest(BaseModel):
    event_id: str = Field(min_length=1)


class SportRefreshRequest(BaseModel):
    sport: str = Field(min_length=1)


class SportRefreshResponse(BaseModel):
    """What the refresh persisted, and what it cost to find out.

    `upstream_contacted` is false when this refresh was served by a fetch that
    was already in flight for the same sport. `data_age_seconds` is how old that
    response was when it was handed over -- `0.0` for a fresh pull.

    The credit fields are populated only when upstream was actually contacted.
    Nulls mean "not reported", never zero: the provider need not send the
    headers, and reporting a free call or an empty balance that we did not
    observe would be worse than reporting nothing.
    """

    sport: str
    events_refreshed: int
    upstream_contacted: bool
    data_age_seconds: float
    credits_spent: int | None
    credits_remaining: int | None
    results: list["QuoteRefreshResponse"]

    @classmethod
    def from_domain(cls, result: SportRefreshResult) -> "SportRefreshResponse":
        quota = result.fetch_report.quota
        return cls(
            sport=result.sport,
            events_refreshed=len(result.summaries),
            upstream_contacted=result.fetch_report.upstream_contacted,
            data_age_seconds=result.fetch_report.data_age_seconds,
            credits_spent=quota.credits_spent if quota else None,
            credits_remaining=quota.credits_remaining if quota else None,
            results=[QuoteRefreshResponse.from_domain(s) for s in result.summaries],
        )


class QuoteRefreshResponse(BaseModel):
    event_id: str
    ingested_quote_count: int
    created_market_count: int
    updated_latest_count: int
    appended_history_count: int
    emitted_event_types: list[str]

    @classmethod
    def from_domain(cls, summary: QuoteRefreshSummary) -> "QuoteRefreshResponse":
        return cls(
            event_id=summary.event_id,
            ingested_quote_count=summary.ingested_quote_count,
            created_market_count=summary.created_market_count,
            updated_latest_count=summary.updated_latest_count,
            appended_history_count=summary.appended_history_count,
            emitted_event_types=summary.emitted_event_types,
        )


class SupportedSportResponse(BaseModel):
    """One sport a refresh may name, in both the provider's terms and ours."""

    key: str
    sport: str
    league: str | None

    @classmethod
    def from_domain(cls, sport: SupportedSport) -> "SupportedSportResponse":
        return cls(key=sport.key, sport=sport.sport, league=sport.league)


class SupportedSportsResponse(BaseModel):
    sports: list[SupportedSportResponse]
