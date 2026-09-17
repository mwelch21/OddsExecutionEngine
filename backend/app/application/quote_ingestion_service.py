import logging
from time import perf_counter
from uuid import uuid4

from backend.app.application.ports import (
    QuoteIngestionProvider,
    QuoteIngestionUnitOfWorkFactory,
    WorkflowEventPublisher,
)
from backend.app.domain.events import (
    build_market_snapshot_created_event,
    build_quote_updated_event,
    build_quotes_refreshed_event,
)
from backend.app.domain.models import Quote, QuoteRefreshSummary, SupportedSport
from backend.app.engines.normalization_engine import NormalizationEngine


class UnsupportedSportError(Exception):
    """A refresh named a sport this system cannot ingest.

    Carries the supported keys so the caller can be told what it should have
    asked for, rather than being handed a bare rejection.
    """

    def __init__(self, sport: str, supported: list[str]) -> None:
        self.sport = sport
        self.supported = supported
        super().__init__(f"Unsupported sport {sport!r}. Supported: {', '.join(supported)}")


class QuoteIngestionService:
    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        unit_of_work_factory: QuoteIngestionUnitOfWorkFactory,
        quote_provider: QuoteIngestionProvider,
        normalization_engine: NormalizationEngine,
        workflow_event_publisher: WorkflowEventPublisher,
        watch_intent_service: object | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._quote_provider = quote_provider
        self._normalization_engine = normalization_engine
        self._workflow_event_publisher = workflow_event_publisher
        # WatchIntentService typed as Any to avoid circular import.
        # The service has an evaluate_for_event(event_id: str) method.
        self._watch_intent_service: object | None = watch_intent_service

    def refresh_quotes(
        self,
        event_id: str,
        quotes_override: list[Quote] | None = None,
        event_metadata: dict[str, object] | None = None,
    ) -> QuoteRefreshSummary:
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
            provider_quotes = (
                quotes_override
                if quotes_override is not None
                else self._quote_provider.list_quotes(event_id)
            )
            normalized_quotes = self._normalization_engine.normalize_quotes(
                event_id,
                provider_quotes,
            )

            with self._unit_of_work_factory() as unit_of_work:
                persistence_result = unit_of_work.persist_quotes(
                    event_id, normalized_quotes, event_metadata
                )

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
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
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

        # Evaluate active watch intents after successful ingestion
        if self._watch_intent_service is not None:
            try:
                self._watch_intent_service.evaluate_for_event(event_id)  # type: ignore[attr-defined]
            except Exception:
                self._logger.exception(
                    "watch_evaluation.failed_after_refresh",
                    extra={"event_id": event_id, "workflow_id": refresh_id},
                )

        self._logger.info(
            "quote_ingestion.completed",
            extra={
                "workflow_id": refresh_id,
                "event_count": len(emitted_event_types),
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return summary

    def list_supported_sports(self) -> list[SupportedSport]:
        """The sports a refresh may name."""
        return self._quote_provider.list_supported_sports()

    def refresh_sport(self, sport: str) -> list[QuoteRefreshSummary]:
        """Refresh all events for a sport."""
        self._assert_sport_supported(sport)
        self._logger.info("sport_refresh.started", extra={"sport": sport})
        started_at = perf_counter()

        all_quotes = self._quote_provider.list_quotes_for_sport(sport)
        summaries: list[QuoteRefreshSummary] = []

        for event_id, quotes in all_quotes.items():
            event_info = self._quote_provider.get_event_info(event_id)
            metadata: dict[str, object] | None = None
            if event_info is not None:
                metadata = {
                    "starts_at": event_info.commence_time,
                    "sport": event_info.sport,
                    "league": event_info.league,
                    "provider": type(self._quote_provider).__name__,
                    "participants": [
                        {
                            "participant_name": p.name,
                            "role": p.role,
                            "side": p.side,
                            "sort_order": p.sort_order,
                        }
                        for p in event_info.participants
                    ],
                }

            summary = self.refresh_quotes(
                event_id,
                quotes_override=quotes,
                event_metadata=metadata,
            )
            summaries.append(summary)

        self._logger.info(
            "sport_refresh.completed",
            extra={
                "sport": sport,
                "event_count": len(summaries),
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return summaries

    def _assert_sport_supported(self, sport: str) -> None:
        """Reject an unknown sport key before it can cost a credit.

        Upstream bills per call whether or not the sport exists, so a typo that
        reaches the provider buys a 404. Checked against the provider's catalog
        rather than the configured sport list: that setting bounds the per-event
        refresh loop and was never a whitelist.
        """
        supported = [entry.key for entry in self._quote_provider.list_supported_sports()]
        if sport not in supported:
            self._logger.warning(
                "sport_refresh.unsupported_sport",
                extra={"sport": sport},
            )
            raise UnsupportedSportError(sport, supported)
