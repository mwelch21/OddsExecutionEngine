import logging

from backend.app.application.ports import QuotaUnitOfWorkFactory
from backend.app.domain.public_events import build_quota_warning_public_event
from backend.app.domain.quota import QuotaReading, QuotaStatus
from backend.app.engines.quota_engine import QuotaEngine


class QuotaService:
    """Records every upstream call's quota and writes the quota warning (ADR-016).

    The provider hands it each reading. The observation and any warning commit in
    one transaction, under a lock, so concurrent refreshes cross the floor once.
    """

    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        unit_of_work_factory: QuotaUnitOfWorkFactory,
        quota_engine: QuotaEngine,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._quota_engine = quota_engine

    def record(self, reading: QuotaReading) -> int:
        """Record one call's observation and return its id, for the refresh link."""
        with self._unit_of_work_factory() as uow:
            uow.lock()
            previous = uow.latest_observation()
            observation = self._quota_engine.observe(reading, previous)
            floor = self._quota_engine.floor(uow.configured_floor(), observation)
            observation_id = uow.add_observation(observation)
            warn = self._quota_engine.should_warn(previous, observation, floor)
            if warn and floor is not None and observation.remaining is not None:
                uow.stage_public_event(
                    build_quota_warning_public_event(
                        remaining=observation.remaining,
                        used=observation.used,
                        floor=floor,
                        observed_at=observation.observed_at,
                    )
                )
        self._logger.info(
            "quota.observed",
            extra={
                "remaining": observation.remaining,
                "used": observation.used,
                "source": observation.source.value,
                "kind": observation.kind.value if observation.kind else None,
                "sport": observation.sport_key,
                "event_id": observation.event_id,
                "credits_spent": observation.credits_spent,
                "out_of_credits": observation.out_of_credits,
                "floor": floor,
                "warned": warn,
            },
        )
        return observation_id

    def status(self) -> QuotaStatus:
        with self._unit_of_work_factory() as uow:
            latest = uow.latest_observation()
            floor = self._quota_engine.floor(uow.configured_floor(), latest)
        return QuotaStatus(
            latest=latest, floor=floor, paused=self._quota_engine.is_paused(latest)
        )
