from datetime import datetime

from pydantic import BaseModel

from backend.app.domain.models import (
    EventPage,
    EventParticipant,
    EventQuoteFreshness,
    EventSummary,
    LineBoard,
    LineBoardMarket,
    MarketType,
    Quote,
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


class LineBoardQuoteResponse(BaseModel):
    """One book's price on the board, carrying both clocks.

    `quoted_at` is when the book last moved this line; `ingested_at` is when we
    pulled it. A line untouched for three days and pulled ten seconds ago is
    three days old, and the board has to be able to show that. `quoted_at` is
    null when the provider exposes no line-movement time, which `line_age_known`
    states outright so an unknown age is never read as freshly moved.
    """

    sportsbook: str
    price: int
    quoted_at: datetime | None
    ingested_at: datetime | None
    line_age_known: bool

    @classmethod
    def from_domain(cls, quote: Quote) -> "LineBoardQuoteResponse":
        return cls(
            sportsbook=quote.sportsbook,
            price=quote.price,
            quoted_at=quote.quoted_at,
            ingested_at=quote.ingested_at,
            line_age_known=quote.line_age_known,
        )


class LineBoardMarketResponse(BaseModel):
    """One market's books, ranked best-first, with the best one named.

    `best_sportsbook` / `best_price` are the head of `quotes`, reported rather
    than left to the client: at an identical price only the engine's tie-break
    decides the winner, and a client sorting for itself can disagree with the
    book a watch on this market would actually fire on. Both are null for a
    market no book is quoting.
    """

    market_type: MarketType
    selection: str
    line: float | None
    best_sportsbook: str | None
    best_price: int | None
    quotes: list[LineBoardQuoteResponse]

    @classmethod
    def from_domain(cls, market: LineBoardMarket) -> "LineBoardMarketResponse":
        return cls(
            market_type=market.market_type,
            selection=market.selection,
            line=market.line,
            best_sportsbook=market.best_sportsbook,
            best_price=market.best_price,
            quotes=[
                LineBoardQuoteResponse.from_domain(quote) for quote in market.quotes
            ],
        )


class LineBoardResponse(BaseModel):
    """One event's whole board in one answer. Deliberately unpaged."""

    event: EventResponse
    markets: list[LineBoardMarketResponse]

    @classmethod
    def from_domain(cls, board: LineBoard) -> "LineBoardResponse":
        return cls(
            event=EventResponse.from_domain(board.event),
            markets=[
                LineBoardMarketResponse.from_domain(market) for market in board.markets
            ],
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
