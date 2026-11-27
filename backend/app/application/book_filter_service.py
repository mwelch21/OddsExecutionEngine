import logging

from backend.app.application.ports import BookFilterUnitOfWorkFactory
from backend.app.domain.book_filter import (
    ALL_BOOKS,
    BookFilter,
    BookFilterStatus,
    UnknownSportsbooksError,
)


class BookFilterService:
    """The allowed-books setting (#136) and the resolver that supplies it.

    `resolve` is the single source of the filter for every read and evaluate
    path. Saving a filter only stores it: no watch is re-evaluated and no
    opportunity changes. The next evaluation reads the new filter.
    """

    _logger = logging.getLogger(__name__)

    def __init__(self, unit_of_work_factory: BookFilterUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def resolve(self) -> BookFilter:
        with self._unit_of_work_factory() as uow:
            return uow.get_book_filter()

    def get_status(self) -> BookFilterStatus:
        with self._unit_of_work_factory() as uow:
            return BookFilterStatus(
                book_filter=uow.get_book_filter(),
                available_sportsbooks=uow.list_seen_sportsbooks(),
            )

    def update(self, book_filter: BookFilter) -> BookFilterStatus:
        """Replace the filter. Raises `UnknownSportsbooksError`, and saves nothing,
        for a book that no stored quote has and the current filter does not hold.

        A held book is kept valid so a book that stopped quoting can still be
        re-saved or removed.
        """
        with self._unit_of_work_factory() as uow:
            available = uow.list_seen_sportsbooks()
            current = uow.get_book_filter()
            known = set(available) | set(current.sportsbooks)
            unknown = [book for book in book_filter.sportsbooks if book not in known]
            if unknown:
                raise UnknownSportsbooksError(unknown, available)
            saved = uow.save_book_filter(book_filter)
        self._logger.info(
            "book_filter.updated",
            extra={"sportsbooks": list(saved.sportsbooks)},
        )
        return BookFilterStatus(book_filter=saved, available_sportsbooks=available)


class AllBooksResolver:
    """A resolver with no stored setting: every book. For wiring without a database."""

    def resolve(self) -> BookFilter:
        return ALL_BOOKS
