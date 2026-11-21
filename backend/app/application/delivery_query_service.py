import logging
from time import perf_counter

from backend.app.application.ports import DeliveryReadUnitOfWorkFactory
from backend.app.domain.deliveries import (
    DeliveryFilter,
    DeliveryLogEntry,
    DeliveryPage,
    StoredDelivery,
)
from backend.app.engines.delivery_error_engine import DeliveryErrorEngine
from backend.app.engines.delivery_subject_engine import DeliverySubjectEngine


class DeliveryQueryService:
    """The delivery log: every notification delivery, newest first (#105).

    Pure read path over what the notifier wrote. Each row's event data becomes a
    one-line subject here and goes no further; its stored error is reduced to an
    allowlisted summary, so no push address or answer body reaches the API.
    """

    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        unit_of_work_factory: DeliveryReadUnitOfWorkFactory,
        subject_engine: DeliverySubjectEngine,
        error_engine: DeliveryErrorEngine,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._subject_engine = subject_engine
        self._error_engine = error_engine

    def list_deliveries(
        self, delivery_filter: DeliveryFilter, page: int = 1, page_size: int = 50
    ) -> DeliveryPage:
        started_at = perf_counter()
        with self._unit_of_work_factory() as uow:
            total_items = uow.count_deliveries(delivery_filter)
            offset = (page - 1) * page_size
            # A page past the end is empty rather than an error, as on GET /events.
            rows = (
                uow.list_deliveries(delivery_filter, limit=page_size, offset=offset)
                if offset < total_items
                else []
            )

        self._logger.info(
            "admin.deliveries.list.completed",
            extra={
                "status": delivery_filter.status,
                "event_type": delivery_filter.event_type,
                "destination_id": delivery_filter.destination_id,
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "returned_count": len(rows),
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return DeliveryPage(
            deliveries=[self._entry(row) for row in rows],
            page=page,
            page_size=page_size,
            total_items=total_items,
        )

    def _entry(self, row: StoredDelivery) -> DeliveryLogEntry:
        return DeliveryLogEntry(
            id=row.id,
            event_id=row.event_id,
            event_type=row.event_type,
            subject=self._subject_engine.subject_for(row.event_type, row.event_data),
            destination_id=row.destination_id,
            destination_label=row.destination_label,
            channel=row.channel,
            status=row.status,
            attempts=row.attempts,
            last_error=self._error_engine.summary(row.last_error),
            created_at=row.created_at,
            ended_at=row.ended_at,
        )
