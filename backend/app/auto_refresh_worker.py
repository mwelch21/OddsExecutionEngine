"""The Auto-Refresh worker: the only process that refreshes on its own (ADR-016).

Same image as the API, different command. It polls every 30s and lets
`AutoRefreshService.run_cycle` decide whether anything is due; with the switch off,
or no watch to serve, a poll makes no upstream call. A Postgres advisory lock keeps
cycles from overlapping however many workers are started.
"""

import logging
import signal
import threading
from types import FrameType

from backend.app.composition import (
    build_auto_refresh_service,
    build_quote_ingestion_service,
    build_watch_intent_service,
)
from backend.app.config import get_settings
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.infrastructure.observability.logging import configure_logging
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.publishers.logging_publisher import (
    LoggingWorkflowEventPublisher,
)

POLL_SECONDS = 30


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    logger = logging.getLogger(__name__)

    session_factory = DatabaseSessionFactory(settings.database_url)
    publisher = LoggingWorkflowEventPublisher()
    price_comparison_service = PriceComparisonService()
    watch_intent_service = build_watch_intent_service(
        settings,
        session_factory,
        publisher,
        price_comparison_service,
        RecommendationEngine(price_comparison_service),
    )
    service = build_auto_refresh_service(
        session_factory,
        build_quote_ingestion_service(settings, session_factory, publisher, watch_intent_service),
    )

    stopping = threading.Event()

    def stop(signum: int, frame: FrameType | None) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    logger.info("auto_refresh.worker_started", extra={"poll_seconds": POLL_SECONDS})
    while not stopping.is_set():
        try:
            service.run_cycle()
        except Exception:
            # A broken poll (database down, say) must not end the worker.
            logger.exception("auto_refresh.cycle_failed")
        stopping.wait(POLL_SECONDS)
    logger.info("auto_refresh.worker_stopped")
    session_factory.engine.dispose()


if __name__ == "__main__":
    main()
