from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from backend.app.application.ports import SystemStatusReadUnitOfWorkFactory
from backend.app.domain.deliveries import DeliveryStatus
from backend.app.domain.system_status import (
    ComponentStatus,
    CreditsMetric,
    DeliveryCount,
    OperationalMetrics,
    SystemSignals,
)
from backend.app.engines.component_status_engine import ComponentStatusEngine
from backend.app.engines.quota_engine import QuotaEngine

# Delivery outcomes are counted over this window (#93).
DELIVERY_WINDOW = timedelta(hours=24)


class SystemStatusQueryService:
    """Component status and operational metrics for the Systems tab (#106).

    Stored records and two cheap probes only: no write, no event, no upstream call.
    """

    def __init__(
        self,
        unit_of_work_factory: SystemStatusReadUnitOfWorkFactory,
        component_status_engine: ComponentStatusEngine,
        quota_engine: QuotaEngine,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._component_status_engine = component_status_engine
        self._quota_engine = quota_engine
        self._clock = clock

    def database_reachable(self) -> bool:
        with self._unit_of_work_factory() as uow:
            return uow.database_reachable()

    def component_statuses(self) -> list[ComponentStatus]:
        observed_at = self._clock()
        with self._unit_of_work_factory() as uow:
            reachable = uow.database_reachable()
            # With the database down the other signals cannot be read: Unknown.
            signals = SystemSignals(
                database_reachable=reachable,
                notifier_listeners=uow.notifier_listener_count() if reachable else None,
                provider_answer=uow.newest_provider_answer() if reachable else None,
                observed_at=observed_at,
            )
        return self._component_status_engine.statuses(signals)

    def metrics(self) -> OperationalMetrics:
        since = self._clock() - DELIVERY_WINDOW
        with self._unit_of_work_factory() as uow:
            last_refresh = uow.last_successful_refresh()
            latest = uow.latest_quota_observation()
            configured_floor = uow.configured_quota_floor()
            counts = uow.delivery_counts_since(since)
            pending = uow.pending_deliveries()

        credits = None
        if latest is not None:
            floor = self._quota_engine.floor(configured_floor, latest)
            # The Credits tab's rule (#120): refused, or nothing left.
            out_of_credits = self._quota_engine.is_out_of_credits(latest)
            credits = CreditsMetric(
                remaining=latest.remaining,
                used=latest.used,
                floor=floor,
                out_of_credits=out_of_credits,
                # Out of credits is below any floor, known or not, as the Credits
                # tab's meter shows it.
                below_floor=out_of_credits
                or self._component_status_engine.credits_below_floor(latest.remaining, floor),
                observed_at=latest.observed_at,
            )
        return OperationalMetrics(
            last_successful_refresh=last_refresh,
            credits=credits,
            deliveries_since=since,
            delivery_counts=[
                DeliveryCount(status=status, count=counts.get(status, 0))
                for status in DeliveryStatus
            ],
            pending_deliveries=pending,
        )
