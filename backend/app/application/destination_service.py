import logging
from datetime import UTC, datetime, timedelta

from backend.app.application.ports import DestinationUnitOfWorkFactory
from backend.app.domain.destinations import Destination, DisabledReason, WebPushKeys
from backend.app.domain.public_events import PublicEvent, build_destination_test_public_event

# One test per destination per window. A test is a real push through the real
# pipeline, so a held-down button must not become a burst at the push service.
TEST_COOLDOWN = timedelta(seconds=10)


class DestinationNotFoundError(Exception):
    def __init__(self, destination_id: str) -> None:
        super().__init__(f"Destination {destination_id} not found.")


class DestinationInactiveError(Exception):
    def __init__(self, destination: Destination) -> None:
        super().__init__(
            f"Destination {destination.id} is disabled ({destination.disabled_reason})."
        )


class SendTestRateLimitedError(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"A test was sent recently; retry in {retry_after_seconds}s.")
        self.retry_after_seconds = retry_after_seconds


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

    def send_test(self, destination_id: str) -> PublicEvent:
        """Queue a test notification for one destination.

        This only writes `destination.test.v1` to the public outbox. The notifier
        turns it into exactly one delivery and sends it like any other event.
        """
        now = datetime.now(UTC)
        with self._unit_of_work_factory() as uow:
            destination = uow.get_destination(destination_id)
            if destination is None:
                raise DestinationNotFoundError(destination_id)
            if not destination.is_active:
                raise DestinationInactiveError(destination)

            last = uow.latest_test_requested_at(destination_id)
            if last is not None:
                aware = last if last.tzinfo else last.replace(tzinfo=UTC)
                wait = aware + TEST_COOLDOWN - now
                if wait > timedelta(0):
                    raise SendTestRateLimitedError(max(1, int(wait.total_seconds() + 0.999)))

            event = build_destination_test_public_event(destination_id=destination_id)
            uow.add_public_event(event)

        self._logger.info(
            "destination.test.queued",
            extra={"destination_id": destination_id, "public_event_id": event.id},
        )
        return event
