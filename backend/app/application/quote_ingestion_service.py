import logging
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from backend.app.application.ports import (
    QuoteIngestionProvider,
    QuoteIngestionUnitOfWorkFactory,
    RefreshRecorder,
    WorkflowEventPublisher,
)
from backend.app.domain.events import (
    build_market_snapshot_created_event,
    build_quote_updated_event,
    build_quotes_refreshed_event,
)
from backend.app.domain.models import (
    EventSport,
    Quote,
    QuoteRefreshSummary,
    SportRefreshResult,
    SupportedSport,
)
from backend.app.domain.refresh_records import (
    RefreshErrorClassifier,
    RefreshRecord,
    RefreshResult,
    RefreshScope,
    RefreshTrigger,
    classify_domain_error,
)
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


class UnknownEventError(Exception):
    """A per-event refresh named an event this system has never stored or seen."""

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(
            f"Unknown event {event_id!r}. Refresh its sport first so the event is known."
        )


class UnresolvableEventSportError(Exception):
    """A per-event refresh found the event, but not a sport the provider can fetch.

    Raised instead of scanning every sport to find the event: that scan is what
    made one event cost more than a whole sport.
    """

    def __init__(self, event_id: str, event_sport: EventSport) -> None:
        self.event_id = event_id
        self.event_sport = event_sport
        super().__init__(
            f"Cannot resolve a provider sport for event {event_id!r} "
            f"(sport={event_sport.sport!r}, league={event_sport.league!r})."
        )


class QuoteIngestionService:
    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        unit_of_work_factory: QuoteIngestionUnitOfWorkFactory,
        quote_provider: QuoteIngestionProvider,
        normalization_engine: NormalizationEngine,
        workflow_event_publisher: WorkflowEventPublisher,
        watch_intent_service: object | None = None,
        refresh_recorder: RefreshRecorder | None = None,
        error_classifier: RefreshErrorClassifier = classify_domain_error,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._quote_provider = quote_provider
        self._normalization_engine = normalization_engine
        self._workflow_event_publisher = workflow_event_publisher
        # WatchIntentService typed as Any to avoid circular import.
        # The service has an evaluate_for_event(event_id: str) method.
        self._watch_intent_service: object | None = watch_intent_service
        self._refresh_recorder = refresh_recorder
        self._error_classifier = error_classifier
        self._clock = clock

    def refresh_quotes(
        self, event_id: str, trigger: RefreshTrigger = RefreshTrigger.MANUAL
    ) -> QuoteRefreshSummary:
        """Refresh one event: one call to the single-event endpoint (ADR-012)."""
        # Resolved before the refresh starts: an unknown or unresolvable event is
        # the caller's mistake, not a refresh, and must cost nothing.
        sport_key = self._resolve_sport_key(event_id)
        started_at = self._clock()
        persisted: list[str] = []
        try:
            summary = self._ingest_event(
                event_id, self._quote_provider.list_quotes(event_id, sport_key), persisted
            )
        except Exception as error:
            self._record_refresh(
                RefreshScope.EVENT,
                sport_key,
                event_id,
                trigger,
                started_at,
                len(persisted),
                error,
            )
            raise
        self._record_refresh(
            RefreshScope.EVENT, sport_key, event_id, trigger, started_at, len(persisted)
        )
        return summary

    def _ingest_event(
        self,
        event_id: str,
        provider_quotes: list[Quote],
        persisted: list[str],
        event_metadata: dict[str, object] | None = None,
    ) -> QuoteRefreshSummary:
        """Ingest one event's quotes. `persisted` gains the event id once its quotes
        commit, so the refresh record counts it even if publishing then fails."""
        started_at = perf_counter()
        refresh_id = str(uuid4())

        self._logger.info(
            "quote_ingestion.started",
            extra={
                "path": "/api/v1/ingestion/quotes/refresh",
                "workflow_id": refresh_id,
                "event_id": event_id,
            },
        )

        try:
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
            persisted.append(event_id)

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

    def check_quota(self) -> None:
        """A free balance check; the provider records what it reports."""
        self._quote_provider.check_quota()

    def refresh_sport(
        self, sport: str, trigger: RefreshTrigger = RefreshTrigger.MANUAL
    ) -> SportRefreshResult:
        """Refresh all events for a sport."""
        self._assert_sport_supported(sport)
        started_at = self._clock()
        persisted: list[str] = []
        try:
            result = self._refresh_sport(sport, persisted)
        except Exception as error:
            # Events committed before the failure stay stored, and are counted.
            self._record_refresh(
                RefreshScope.SPORT, sport, None, trigger, started_at, len(persisted), error
            )
            raise
        self._record_refresh(
            RefreshScope.SPORT, sport, None, trigger, started_at, len(persisted)
        )
        return result

    def _refresh_sport(self, sport: str, persisted: list[str]) -> SportRefreshResult:
        self._logger.info("sport_refresh.started", extra={"sport": sport})
        started_at = perf_counter()

        all_quotes, fetch_report = self._quote_provider.list_quotes_for_sport(sport)
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

            summary = self._ingest_event(event_id, quotes, persisted, event_metadata=metadata)
            summaries.append(summary)

        # Every sport-wide pull, manual or automatic, restarts that sport's
        # Auto-Refresh cooldown (ADR-016). Only reached once the pull succeeded.
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.record_sport_refreshed(sport, datetime.now(UTC))

        self._logger.info(
            "sport_refresh.completed",
            extra={
                "sport": sport,
                "event_count": len(summaries),
                "upstream_contacted": fetch_report.upstream_contacted,
                "credits_spent": (
                    fetch_report.quota.credits_spent if fetch_report.quota else None
                ),
                "credits_remaining": (
                    fetch_report.quota.credits_remaining if fetch_report.quota else None
                ),
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return SportRefreshResult(
            sport=sport,
            summaries=summaries,
            fetch_report=fetch_report,
        )

    def _record_refresh(
        self,
        scope: RefreshScope,
        sport_key: str,
        event_id: str | None,
        trigger: RefreshTrigger,
        started_at: datetime,
        events_refreshed: int,
        error: Exception | None = None,
    ) -> None:
        """Append the refresh record once ingestion has settled (#96).

        Its own transaction, so a refresh that rolled back is still recorded, and a
        failure here is logged, never raised: the record must not fail the refresh.
        """
        if self._refresh_recorder is None:
            return
        result = RefreshResult.from_error(error, self._error_classifier)
        try:
            self._refresh_recorder.record(
                RefreshRecord(
                    scope=scope,
                    sport_key=sport_key,
                    event_id=event_id,
                    trigger=trigger,
                    started_at=started_at,
                    finished_at=self._clock(),
                    outcome=result.outcome,
                    error_code=result.error_code,
                    error=result.error,
                    events_refreshed=events_refreshed,
                )
            )
        except Exception:
            self._logger.exception(
                "refresh_record.write_failed",
                extra={"sport": sport_key, "event_id": event_id, "outcome": result.outcome.value},
            )

    def _resolve_sport_key(self, event_id: str) -> str:
        """The provider sport key for one event, found without a paid call.

        Stored events come first; the provider's in-process knowledge covers an
        event it has seen but nothing has stored a sport for yet. The (sport, league) pair
        is matched against the provider's own catalog, so this never guesses a
        key that upstream would bill a 404 for.
        """
        with self._unit_of_work_factory() as unit_of_work:
            event_sport = unit_of_work.get_event_sport(event_id)
        if event_sport is None or event_sport.sport is None:
            known = self._quote_provider.get_event_info(event_id)
            if known is not None:
                event_sport = EventSport(sport=known.sport, league=known.league)
            elif event_sport is None:
                raise UnknownEventError(event_id)

        for entry in self._quote_provider.list_supported_sports():
            if (entry.sport, entry.league) == (event_sport.sport, event_sport.league):
                return entry.key
        raise UnresolvableEventSportError(event_id, event_sport)

    def _assert_sport_supported(self, sport: str) -> None:
        """Reject an unknown sport key before it can cost a credit.

        Upstream bills per call whether or not the sport exists, so a typo that
        reaches the provider buys a 404. Checked against the provider's catalog.
        """
        supported = [entry.key for entry in self._quote_provider.list_supported_sports()]
        if sport not in supported:
            self._logger.warning(
                "sport_refresh.unsupported_sport",
                extra={"sport": sport},
            )
            raise UnsupportedSportError(sport, supported)
