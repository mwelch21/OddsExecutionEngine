from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.book_filter import BookFilter
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    book_filter_settings_table,
    market_quotes_latest_table,
)
from backend.app.infrastructure.persistence.upsert import upsert

SETTINGS_ROW_ID = 1


class SqlAlchemyBookFilterUnitOfWork:
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> "SqlAlchemyBookFilterUnitOfWork":
        self._session = self._session_factory.create_session()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        session = self._require_session()
        try:
            if exc_type is None:
                session.commit()
            else:
                session.rollback()
        finally:
            session.close()
            self._session = None

    def get_book_filter(self) -> BookFilter:
        books = (
            self._require_session()
            .execute(
                select(book_filter_settings_table.c.sportsbooks).where(
                    book_filter_settings_table.c.id == SETTINGS_ROW_ID
                )
            )
            .scalar_one_or_none()
        )
        return BookFilter(sportsbooks=tuple(books or ()))

    def save_book_filter(self, book_filter: BookFilter) -> BookFilter:
        upsert(
            self._require_session(),
            book_filter_settings_table,
            {
                "id": SETTINGS_ROW_ID,
                "sportsbooks": list(book_filter.sportsbooks),
                "updated_at": datetime.now(UTC),
            },
            key_columns=["id"],
        )
        return self.get_book_filter()

    def list_seen_sportsbooks(self) -> list[str]:
        # Latest quotes only: every book a refresh has stored is there, and the
        # history table is too large to scan for a picker.
        rows = self._require_session().execute(
            select(market_quotes_latest_table.c.sportsbook)
            .distinct()
            .order_by(market_quotes_latest_table.c.sportsbook)
        )
        return [str(book) for book in rows.scalars().all()]

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Book filter unit of work must be entered before use.")
        return self._session
