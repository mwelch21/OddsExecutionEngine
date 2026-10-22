import logging

from backend.app.application.ports import DestinationUnitOfWorkFactory
from backend.app.domain.destinations import Destination, DisabledReason, WebPushKeys


class DestinationService:
    """Registers and lists the places public events are delivered to."""

    _logger = logging.getLogger(__name__)

    def __init__(self, unit_of_work_factory: DestinationUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def register_web_push(
        self, address: str, keys: WebPushKeys, label: str
    ) -> tuple[Destination, bool]:
        """Idempotent on the push endpoint. Returns the destination and whether it is new.

        A browser re-subscribing hands back fresh keys for the same endpoint, so the
        keys are always refreshed. A `gone` destination is revived, because a valid
        subscription from the browser is exactly what "gone" was waiting for. One the
        operator removed stays removed: re-enabling it is the operator's call.
        """
        with self._unit_of_work_factory() as uow:
            existing = uow.get_web_push_destination(address)
            if existing is None:
                destination = uow.create_web_push_destination(address, keys, label)
                created = True
            else:
                destination = uow.refresh_web_push_destination(
                    existing.id,
                    keys,
                    reactivate=existing.disabled_reason is DisabledReason.GONE,
                )
                created = False

        self._logger.info(
            "destination.web_push.registered",
            extra={
                "destination_id": destination.id,
                "is_new": created,
                "active": destination.is_active,
            },
        )
        return destination, created

    def list_destinations(self) -> list[Destination]:
        with self._unit_of_work_factory() as uow:
            return uow.list_destinations()
