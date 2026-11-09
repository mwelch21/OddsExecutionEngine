from collections.abc import Callable
from datetime import UTC, datetime

from backend.app.application.ports import CreditReadUnitOfWorkFactory
from backend.app.domain.credits import CreditBurn, QuotaHistoryPoint
from backend.app.engines.credit_history_engine import CreditHistoryEngine


class CreditQueryService:
    """The Credits tab's reads (#104): balance history and burn per month.

    Stored quota observations only, one per upstream call. No write, no upstream call.
    """

    def __init__(
        self,
        unit_of_work_factory: CreditReadUnitOfWorkFactory,
        history_engine: CreditHistoryEngine,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._history_engine = history_engine
        self._clock = clock

    def quota_history(self, days: int) -> list[QuotaHistoryPoint]:
        """The last remaining balance per hour over the last `days` days, oldest first.

        An hour with no call has no point; the chart carries the balance across it.
        """
        since = self._history_engine.history_since(self._clock(), days)
        with self._unit_of_work_factory() as uow:
            readings = uow.list_remaining(since)
        return self._history_engine.hourly(readings)

    def credit_burn(self, month: str | None = None) -> CreditBurn:
        """Credits spent in a UTC calendar month; this month when none is named.

        Raises `InvalidMonthError` for anything but `YYYY-MM`.
        """
        month = month or self._history_engine.month_of(self._clock())
        starts_at, ends_at = self._history_engine.month_window(month)
        with self._unit_of_work_factory() as uow:
            rows = uow.sum_burn(starts_at, ends_at)
        return self._history_engine.burn(month, rows)
