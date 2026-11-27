"""The allowed-books filter (#136): which sportsbooks the operator can bet at.

A refresh bills `markets x regions`, so it returns every book in the region for
the same credits. Ingestion keeps storing all of them; the filter applies only
where quotes are read and evaluated: the line board, the events-list freshness,
recommendation and watch evaluation.

Empty means all books, the same convention as the sport focus (#132). Engines
take a `BookFilter` as an argument and never read where it is stored. Today one
global setting supplies it; after auth (#14) a per-user setting will, through the
same resolver port, with no engine change.
"""

from collections.abc import Iterable

from pydantic import field_validator

from backend.app.domain.base import DomainModel
from backend.app.domain.models import Quote


class BookFilter(DomainModel):
    """Sportsbook names a quote must come from, sorted and de-duplicated.

    The names are the exact `sportsbook` strings stored on quotes. Empty admits
    every book.
    """

    sportsbooks: tuple[str, ...] = ()

    @field_validator("sportsbooks", mode="after")
    @classmethod
    def _sorted_unique(cls, books: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(books)))

    @property
    def allows_all(self) -> bool:
        return not self.sportsbooks

    def admits(self, sportsbook: str) -> bool:
        return self.allows_all or sportsbook in self.sportsbooks

    def apply(self, quotes: Iterable[Quote]) -> list[Quote]:
        """The quotes from admitted books, in their original order."""
        return [quote for quote in quotes if self.admits(quote.sportsbook)]


ALL_BOOKS = BookFilter()


class BookFilterStatus(DomainModel):
    """The filter in force, and the books the picker can offer.

    `available_sportsbooks` are the distinct books in stored latest quotes, read
    from the database only; no provider call.
    """

    book_filter: BookFilter
    available_sportsbooks: list[str]


class UnknownSportsbooksError(Exception):
    """A filter named books that no stored quote has and the filter did not hold."""

    def __init__(self, unknown: list[str], available: list[str]) -> None:
        self.unknown = unknown
        self.available = available
        super().__init__(
            f"Unknown sportsbooks {', '.join(unknown)}. "
            f"Seen in stored quotes: {', '.join(available) or 'none'}"
        )
