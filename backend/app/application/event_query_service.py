import logging
from datetime import UTC, datetime
from time import perf_counter

from backend.app.application.ports import EventReadUnitOfWorkFactory
from backend.app.domain.models import EventFilter, EventPage


class EventQueryService:
    """Browse stored events, page by page.

    Pure read path: no unit-of-work events are staged and nothing is published.
    `now` is taken once per request so the count and the page agree on which
    events have already started.
    """

    _logger = logging.getLogger(__name__)

    def __init__(self, unit_of_work_factory: EventReadUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def list_events(
        self,
        event_filter: EventFilter,
        page: int = 1,
        page_size: int = 25,
    ) -> EventPage:
        started_at = perf_counter()
        now = datetime.now(UTC)

        try:
            with self._unit_of_work_factory() as uow:
                total_events = uow.count_events(event_filter, now)
                offset = (page - 1) * page_size
                # A page past the end is empty rather than an error: the set moves
                # under the reader as events start.
                events = (
                    uow.list_events(event_filter, now, limit=page_size, offset=offset)
                    if offset < total_events
                    else []
                )
        except Exception:
            self._logger.exception(
                "events.list.failed",
                extra={
                    "path": "/events",
                    "league": event_filter.league,
                    "sport": event_filter.sport,
                    "page": page,
                    "page_size": page_size,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise

        self._logger.info(
            "events.list.completed",
            extra={
                "path": "/events",
                "league": event_filter.league,
                "sport": event_filter.sport,
                "include_started": event_filter.include_started,
                "page": page,
                "page_size": page_size,
                "total_events": total_events,
                "returned_count": len(events),
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return EventPage(
            events=events,
            page=page,
            page_size=page_size,
            total_events=total_events,
        )
