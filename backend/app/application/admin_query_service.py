from backend.app.application.ports import AdminReadUnitOfWorkFactory
from backend.app.domain.refresh_records import RefreshRecordFilter, RefreshRecordPage


class AdminQueryService:
    """The Admin view's reads (#93). Stored records only: no write, no upstream call."""

    def __init__(self, unit_of_work_factory: AdminReadUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def list_refreshes(
        self, refresh_filter: RefreshRecordFilter, page: int = 1, page_size: int = 50
    ) -> RefreshRecordPage:
        """The refresh log, newest first. A page past the end is empty, not an error."""
        with self._unit_of_work_factory() as uow:
            total = uow.count_refreshes(refresh_filter)
            records = uow.list_refreshes(
                refresh_filter, limit=page_size, offset=(page - 1) * page_size
            )
        return RefreshRecordPage(records=records, page=page, page_size=page_size, total_items=total)
