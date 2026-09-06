import logging
from time import perf_counter
from uuid import uuid4

from backend.app.application.ports import (
    QuoteIngestionProvider,
    QuoteIngestionUnitOfWorkFactory,
    WorkflowEventPublisher,
)
from backend.app.application.timing import elapsed_ms
from backend.app.domain.events import (
    build_market_snapshot_created_event,
    build_quote_updated_event,
    build_quotes_refreshed_event,
)
from backend.app.domain.models import QuoteRefreshSummary
from backend.app.engines.normalization_engine import NormalizationEngine


class QuoteIngestionService:
    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        unit_of_work_factory: QuoteIngestionUnitOfWorkFactory,
        quote_provider: QuoteIngestionProvider,
        normalization_engine: NormalizationEngine,
        workflow_event_publisher: WorkflowEventPublisher,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._quote_provider = quote_provider
        self._normalization_engine = normalization_engine
        self._workflow_event_publisher = workflow_event_publisher

    def refresh_quotes(self, event_id: str) -> QuoteRefreshSummary:
        started_at = perf_counter()
        refresh_id = str(uuid4())

        self._logger.info(
            "quote_ingestion.started",
            extra={
                "path": "/ingestion/quotes/refresh",
                "workflow_id": refresh_id,
                "event_id": event_id,
            },
        )

        try:
            provider_quotes = self._quote_provider.list_quotes(event_id)
            normalized_quotes = self._normalization_engine.normalize_quotes(
                event_id,
                provider_quotes,
            )

            with self._unit_of_work_factory() as unit_of_work:
                persistence_result = unit_of_work.persist_quotes(event_id, normalized_quotes)

                for persisted_quote in persistence_result.persisted_quotes:
                    if persisted_quote.market_created:
                        unit_of_work.stage_event(
                            build_market_snapshot_created_event(
                                refresh_id=refresh_id,
                                persisted_quote=persisted_quote,
                            )
                        )
                    unit_of_work.stage_event(
                        build_quote_updated_event(
                            refresh_id=refresh_id,
                            persisted_quote=persisted_quote,
                        )
                    )

                unit_of_work.stage_event(
                    build_quotes_refreshed_event(
                        refresh_id=refresh_id,
                        result=persistence_result,
                    )
                )

            self._workflow_event_publisher.publish(unit_of_work.committed_events)
        except Exception:
            self._logger.exception(
                "quote_ingestion.failed",
                extra={
                    "workflow_id": refresh_id,
                    "duration_ms": elapsed_ms(started_at),
                },
            )
            raise

        emitted_event_types = [event.event_type for event in unit_of_work.committed_events]
        summary = QuoteRefreshSummary(
            event_id=event_id,
            ingested_quote_count=len(persistence_result.persisted_quotes),
            created_market_count=persistence_result.created_market_count,
            updated_latest_count=persistence_result.updated_latest_count,
            appended_history_count=persistence_result.appended_history_count,
            emitted_event_types=emitted_event_types,
        )

        self._logger.info(
            "quote_ingestion.completed",
            extra={
                "workflow_id": refresh_id,
                "event_count": len(emitted_event_types),
                "duration_ms": elapsed_ms(started_at),
            },
        )
        return summary
