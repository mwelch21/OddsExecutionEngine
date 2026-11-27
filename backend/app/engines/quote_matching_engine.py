from backend.app.domain.book_filter import ALL_BOOKS, BookFilter
from backend.app.domain.models import OrderIntent, Quote


class QuoteMatchingEngine:
    def match_quotes(
        self,
        intent: OrderIntent,
        quotes: list[Quote],
        book_filter: BookFilter = ALL_BOOKS,
    ) -> list[Quote]:
        """Quotes on the intent's market from books `book_filter` admits (#136).

        Ranking, fillability and the nearest miss all work on this result, so a
        book outside the filter can never be recommended or be the nearest miss.
        """
        return [
            quote
            for quote in quotes
            if quote.event_id == intent.event_id
            and quote.market_type == intent.market_type
            and quote.selection == intent.selection
            and quote.line == intent.line
            and book_filter.admits(quote.sportsbook)
        ]
