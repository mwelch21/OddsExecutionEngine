import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4

from backend.app.application.ports import (
    QuoteIngestionProvider,
    QuoteIngestionUnitOfWork,
    QuoteIngestionUnitOfWorkFactory,
    RefreshRecorder,
    WorkflowEventPublisher,
)
from backend.app.application.watch_expiry import WatchExpirer
from backend.app.domain.events import (
    build_market_snapshot_created_event,
    build_quote_updated_event,
    build_quotes_refreshed_event,
)
from backend.app.domain.models import (
    EventObservation,
    EventSport,
    EventStatus,
    ProviderFetchReport,
    Quote,
    QuoteRefreshSummary,
    SportRefreshResult,
    SupportedSport,
    WatchIntent,
)
from backend.app.domain.quota import link_observation, linked_observation
from backend.app.domain.refresh_records import (
    RefreshErrorClassifier,
    RefreshRecord,
    RefreshResult,
    RefreshScope,
    RefreshTrigger,
    classify_domain_error,
)
from backend.app.engines.event_status_engine import EventStatusEngine
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
        event_status_engine: EventStatusEngine | None = None,
        watch_expirer: WatchExpirer | None = None,
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
        self._event_status_engine = event_status_engine or EventStatusEngine()
        self._watch_expirer = watch_expirer or WatchExpirer()

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
            quotes, fetch_report = self._quote_provider.list_quotes(event_id, sport_key)
            try:
                observation = self._observe_event_refresh(event_id, quotes, fetch_report)
                summary = self._ingest_event(
                    event_id, quotes, persisted, observation=observation
                )
            except Exception as error:
                link_observation(error, fetch_report.observation_id)
                raise
        except Exception as error:
            self._record_refresh(
                RefreshScope.EVENT,
                sport_key,
                event_id,
                trigger,
                started_at,
                len(persisted),
                linked_observation(error),
                error,
            )
            raise
        self._record_refresh(
            RefreshScope.EVENT,
            sport_key,
            event_id,
            trigger,
            started_at,
            len(persisted),
            fetch_report.observation_id,
        )
        return summary

    def _ingest_event(
        self,
        event_id: str,
        provider_quotes: list[Quote],
        persisted: list[str],
        event_metadata: dict[str, object] | None = None,
        observation: EventObservation | None = None,
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
            if observation is not None:
                phase = self._event_status_engine.line_phase(observation.status)
                normalized_quotes = [
                    quote.model_copy(update={"phase": phase}) for quote in normalized_quotes
                ]

            with self._unit_of_work_factory() as unit_of_work:
                persistence_result = unit_of_work.persist_quotes(
                    event_id, normalized_quotes, event_metadata, observation
                )
                if persistence_result.status_written:
                    self._expire_closed_windows(unit_of_work, [event_id])

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
                RefreshScope.SPORT,
                sport,
                None,
                trigger,
                started_at,
                len(persisted),
                linked_observation(error),
                error,
            )
            raise
        self._record_refresh(
            RefreshScope.SPORT,
            sport,
            None,
            trigger,
            started_at,
            len(persisted),
            result.fetch_report.observation_id,
        )
        return result

    def _refresh_sport(self, sport: str, persisted: list[str]) -> SportRefreshResult:
        self._logger.info("sport_refresh.started", extra={"sport": sport})
        started_at = perf_counter()

        all_quotes, fetch_report = self._quote_provider.list_quotes_for_sport(sport)
        try:
            return self._ingest_sport(sport, all_quotes, fetch_report, persisted, started_at)
        except Exception as error:
            # The call was made; a failure after it still links the refresh to it.
            link_observation(error, fetch_report.observation_id)
            raise

    def _ingest_sport(
        self,
        sport: str,
        all_quotes: dict[str, list[Quote]],
        fetch_report: ProviderFetchReport,
        persisted: list[str],
        started_at: float,
    ) -> SportRefreshResult:
        summaries: list[QuoteRefreshSummary] = []
        now = self._observed_at(fetch_report)

        for event_id, quotes in all_quotes.items():
            event_info = self._quote_provider.get_event_info(event_id)
            metadata: dict[str, object] | None = None
            starts_at = (
                event_info.commence_time
                if event_info is not None
                else self._stored_starts_at(event_id)
            )
            # Offered in this pull, so live once started (#38). The start time
            # travels with the status so a moved kickoff is stored with it.
            observation = EventObservation(
                status=self._event_status_engine.observe_offered(starts_at, now),
                observed_at=now,
                starts_at=event_info.commence_time if event_info is not None else None,
            )
            if event_info is not None:
                metadata = {
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

            summary = self._ingest_event(
                event_id, quotes, persisted, event_metadata=metadata, observation=observation
            )
            summaries.append(summary)

        # Every sport-wide pull, manual or automatic, restarts that sport's
        # Auto-Refresh cooldown (ADR-016). Only reached once the pull succeeded.
        with self._unit_of_work_factory() as unit_of_work:
            ended = self._end_absent_events(unit_of_work, sport, set(all_quotes), now)
            expired = self._expire_closed_windows(unit_of_work, ended)
            unit_of_work.record_sport_refreshed(sport, datetime.now(UTC))
        if expired:
            self._workflow_event_publisher.publish(unit_of_work.committed_events)

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

    def _observe_event_refresh(
        self, event_id: str, quotes: list[Quote], fetch_report: ProviderFetchReport
    ) -> EventObservation:
        """A per-event refresh's observation: ended on a 404 or empty answer (#38)."""
        offered = (
            fetch_report.event_offered
            if fetch_report.event_offered is not None
            else bool(quotes)
        )
        known = self._quote_provider.get_event_info(event_id) if offered else None
        observed_start = known.commence_time if known is not None else None
        starts_at = (
            observed_start if observed_start is not None else self._stored_starts_at(event_id)
        )
        observed_at = self._observed_at(fetch_report)
        status = self._event_status_engine.observe_event_refresh(
            offered=offered, starts_at=starts_at, now=observed_at
        )
        if status is EventStatus.ENDED:
            self._logger.info("quote_ingestion.event_ended", extra={"event_id": event_id})
        return EventObservation(status=status, observed_at=observed_at, starts_at=observed_start)

    def _observed_at(self, fetch_report: ProviderFetchReport) -> datetime:
        """When the provider's response arrived, so processing delay cannot reorder
        two answers. A provider that does not say falls back to the ingestion
        clock less the data's age."""
        if fetch_report.answered_at is not None:
            return fetch_report.answered_at
        return self._clock() - timedelta(seconds=fetch_report.data_age_seconds)

    def _stored_starts_at(self, event_id: str) -> datetime | None:
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.get_event_starts_at(event_id)

    def _end_absent_events(
        self,
        unit_of_work: QuoteIngestionUnitOfWork,
        sport_key: str,
        offered: set[str],
        now: datetime,
    ) -> list[str]:
        """Mark ended each started event of this sport the pull no longer offered.

        Returns the events it ended; one whose stored observation is newer is
        left as it was and is not returned.
        """
        catalog = {entry.key: entry for entry in self._quote_provider.list_supported_sports()}
        entry = catalog.get(sport_key)
        if entry is None:
            return []
        stored = unit_of_work.list_event_starts(entry.sport, entry.league)
        ended = sorted(
            event_id
            for event_id, starts_at in stored.items()
            if event_id not in offered
            and self._event_status_engine.observe_absent_from_sport_pull(starts_at, now)
            is EventStatus.ENDED
        )
        ended = unit_of_work.set_event_status(ended, EventStatus.ENDED, now)
        if ended:
            self._logger.info(
                "sport_refresh.events_ended",
                extra={"sport": sport_key, "event_ids": ended},
            )
        return ended

    def _expire_closed_windows(
        self, unit_of_work: QuoteIngestionUnitOfWork, written_event_ids: list[str]
    ) -> list[WatchIntent]:
        """Expire the watches whose window the stored status now closes (ADR-017).

        Runs in the transaction that wrote the status, and only for events whose
        guarded status write succeeded: a stale observation closes nothing, not
        even a TTL. The status write holds the event row lock until commit, so a
        watch created concurrently either waits and reads the new status, or
        committed first and is seen here. Stages a workflow event per watch,
        never a notification. Returns the watches it expired.
        """
        if not written_event_ids:
            return []
        lifecycles = unit_of_work.get_event_lifecycles(written_event_ids)
        intents = unit_of_work.list_active_watch_intents(sorted(lifecycles))
        retired = self._watch_expirer.expire(
            unit_of_work, intents, lifecycles, self._clock()
        )
        if retired:
            self._logger.info(
                "quote_ingestion.watches_expired",
                extra={"event_ids": sorted(lifecycles), "watch_count": len(retired)},
            )
        return retired

    def _record_refresh(
        self,
        scope: RefreshScope,
        sport_key: str,
        event_id: str | None,
        trigger: RefreshTrigger,
        started_at: datetime,
        events_refreshed: int,
        observation_id: int | None,
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
                    quota_observation_id=observation_id,
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
