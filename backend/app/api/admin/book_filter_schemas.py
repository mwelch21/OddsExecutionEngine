from pydantic import BaseModel, Field

from backend.app.domain.book_filter import BookFilter, BookFilterStatus


class BookFilterRequest(BaseModel):
    """A full replacement of the allowed books (#136).

    Names are the exact `sportsbook` strings on stored quotes. Empty, or an
    omitted field, means all books. Duplicates collapse and the stored order is
    sorted. A name that no stored quote has, and that the current filter does
    not already hold, is a 422.
    """

    sportsbooks: list[str] = Field(default_factory=list, max_length=200)

    def to_domain(self) -> BookFilter:
        return BookFilter(sportsbooks=tuple(self.sportsbooks))


class BookFilterResponse(BaseModel):
    # The allowed books, sorted; empty = all books.
    sportsbooks: list[str]
    # Distinct books in stored latest quotes, sorted: the picker's options. A DB
    # read, never the provider.
    available_sportsbooks: list[str]

    @classmethod
    def from_domain(cls, status: BookFilterStatus) -> "BookFilterResponse":
        return cls(
            sportsbooks=list(status.book_filter.sportsbooks),
            available_sportsbooks=status.available_sportsbooks,
        )
