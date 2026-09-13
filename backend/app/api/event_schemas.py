from datetime import datetime

from pydantic import BaseModel

from backend.app.domain.models import (
    EventPage,
    EventParticipant,
    EventQuoteFreshness,
    EventSummary,
)


class EventParticipantResponse(BaseModel):
    name: str
    role: str
    side: str | None

    @classmethod
    def from_domain(cls, participant: EventParticipant) -> "EventParticipantResponse":
        return cls(
            name=participant.name,
            role=participant.role,
            side=participant.side,
        )


class EventQuoteFreshnessResponse(BaseModel):
    """Both clocks, never collapsed into one.

    `last_ingested_at` is when we pulled; `oldest_line_quoted_at` is the oldest
    line among the books that report one. Nulls mean "no such fact yet" — an
    unrefreshed event, or books that expose no line-movement time — and are never
    stand-ins for zero age. `books_with_unknown_line_age` says how many of
    `book_count` books the reported oldest does not account for.

    `quote_count` counts stored quotes and `book_count` counts distinct books;
    one book quoting both sides of three markets is six quotes and one book.
    """

    quote_count: int
    book_count: int
    last_ingested_at: datetime | None
    oldest_line_quoted_at: datetime | None
    books_with_unknown_line_age: int

    @classmethod
    def from_domain(
        cls, freshness: EventQuoteFreshness
    ) -> "EventQuoteFreshnessResponse":
        return cls(
            quote_count=freshness.quote_count,
            book_count=freshness.book_count,
            last_ingested_at=freshness.last_ingested_at,
            oldest_line_quoted_at=freshness.oldest_line_quoted_at,
            books_with_unknown_line_age=freshness.books_with_unknown_line_age,
        )


class EventResponse(BaseModel):
    id: str
    sport: str | None
    league: str | None
    status: str
    starts_at: datetime | None
    participants: list[EventParticipantResponse]
    quotes: EventQuoteFreshnessResponse

    @classmethod
    def from_domain(cls, event: EventSummary) -> "EventResponse":
        return cls(
            id=event.id,
            sport=event.sport,
            league=event.league,
            status=event.status,
            starts_at=event.starts_at,
            participants=[
                EventParticipantResponse.from_domain(participant)
                for participant in event.participants
            ],
            quotes=EventQuoteFreshnessResponse.from_domain(event.quotes),
        )


class EventListResponse(BaseModel):
    events: list[EventResponse]
    page: int
    page_size: int
    total_events: int
    total_pages: int

    @classmethod
    def from_domain(cls, page: EventPage) -> "EventListResponse":
        return cls(
            events=[EventResponse.from_domain(event) for event in page.events],
            page=page.page,
            page_size=page.page_size,
            total_events=page.total_events,
            total_pages=page.total_pages,
        )
