"""Read side of the Admin view. Every read is DB-only and costs no credits.

Filtering and paging happen in SQL, as for the event browse, so the totals always
match the rows.
"""

from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.domain.refresh_records import RefreshRecord, RefreshRecordFilter
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.refresh_records import refresh_record_from_row
from backend.app.infrastructure.persistence.schema import (
    quota_observations_table,
    refresh_records_table,
)

SelectT = TypeVar("SelectT", bound=Select[tuple[Any, ...]])


class SqlAlchemyAdminReadUnitOfWork:
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> "SqlAlchemyAdminReadUnitOfWork":
        self._session = self._session_factory.create_session()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        session = self._require_session()
        # Nothing here writes; only the read transaction to release.
        session.rollback()
        session.close()
        self._session = None

    def count_refreshes(self, refresh_filter: RefreshRecordFilter) -> int:
        query = select(func.count()).select_from(refresh_records_table)
        return int(
            self._require_session().execute(_filter_refreshes(query, refresh_filter)).scalar_one()
        )

    def list_refreshes(
        self, refresh_filter: RefreshRecordFilter, limit: int, offset: int
    ) -> list[RefreshRecord]:
        query = (
            # Cost is read through the linked upstream call, never stored twice (#104).
            select(refresh_records_table, quota_observations_table.c.credits_spent)
            .outerjoin(
                quota_observations_table,
                refresh_records_table.c.quota_observation_id == quota_observations_table.c.id,
            )
            # Newest first; id breaks ties so paging never repeats or skips a row.
            .order_by(
                refresh_records_table.c.started_at.desc(),
                refresh_records_table.c.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = (
            self._require_session()
            .execute(_filter_refreshes(query, refresh_filter))
            .mappings()
            .all()
        )
        return [refresh_record_from_row(row) for row in rows]

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Admin read unit of work must be entered before use.")
        return self._session


def _filter_refreshes(query: SelectT, refresh_filter: RefreshRecordFilter) -> SelectT:
    if refresh_filter.sport_key is not None:
        query = query.where(refresh_records_table.c.sport_key == refresh_filter.sport_key)
    if refresh_filter.trigger is not None:
        query = query.where(refresh_records_table.c.trigger == refresh_filter.trigger.value)
    if refresh_filter.outcome is not None:
        query = query.where(refresh_records_table.c.outcome == refresh_filter.outcome.value)
    if refresh_filter.error_code is not None:
        query = query.where(
            refresh_records_table.c.error_code == refresh_filter.error_code.value
        )
    return query
