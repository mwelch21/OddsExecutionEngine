from pydantic import BaseModel, Field

from backend.app.domain.models import QuoteRefreshSummary


class QuoteRefreshRequest(BaseModel):
    event_id: str = Field(min_length=1)


class SportRefreshRequest(BaseModel):
    sport: str = Field(min_length=1)


class SportRefreshResponse(BaseModel):
    sport: str
    events_refreshed: int
    results: list["QuoteRefreshResponse"]


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
