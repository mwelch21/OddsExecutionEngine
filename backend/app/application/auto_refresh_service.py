import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import perf_counter

from backend.app.application.ports import (
    AutoRefreshCycleLock,
    AutoRefreshUnitOfWorkFactory,
)
from backend.app.application.quota_service import QuotaService
from backend.app.application.quote_ingestion_service import QuoteIngestionService
from backend.app.domain.auto_refresh import (
    AutoRefreshCycleReport,
    AutoRefreshOutcome,
    AutoRefreshSettings,
    AutoRefreshStatus,
    RefreshOutcomeStatus,
)
from backend.app.domain.models import EventSport
from backend.app.domain.quota import OutOfUsageCreditsError
from backend.app.domain.refresh_records import RefreshResult, RefreshTrigger
from backend.app.engines.auto_refresh_cadence_engine import AutoRefreshCadenceEngine


class AutoRefreshService:
    """The operator's Auto-Refresh switch and the worker cycle it drives (ADR-016).

    The only automatic path to the provider. A cycle spends nothing unless the
    switch is on, some watch can use the result, and that sport's cooldown has
    elapsed.
    """

    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        unit_of_work_factory: AutoRefreshUnitOfWorkFactory,
        cycle_lock: AutoRefreshCycleLock,
        quote_ingestion_service: QuoteIngestionService,
        cadence_engine: AutoRefreshCadenceEngine,
        quota_service: QuotaService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._cycle_lock = cycle_lock
        self._quote_ingestion_service = quote_ingestion_service
        self._cadence_engine = cadence_engine
        self._quota_service = quota_service
        self._clock = clock

    def get_status(self) -> AutoRefreshStatus:
        with self._unit_of_work_factory() as uow:
            settings = uow.get_settings()
            last_outcome = uow.get_last_outcome()
        return AutoRefreshStatus(
            settings=settings,
            last_outcome=last_outcome,
            quota=self._quota_service.status(),
        )

    def update_settings(self, settings: AutoRefreshSettings) -> AutoRefreshStatus:
        with self._unit_of_work_factory() as uow:
            saved = uow.save_settings(settings)
            last_outcome = uow.get_last_outcome()
        self._logger.info(
            "auto_refresh.settings_updated",
            extra={"enabled": saved.enabled, "interval_minutes": saved.interval_minutes},
        )
        return AutoRefreshStatus(
            settings=saved, last_outcome=last_outcome, quota=self._quota_service.status()
        )

    def run_cycle(self) -> AutoRefreshCycleReport:
        """One poll: refresh every watched sport whose cooldown has elapsed."""
        with self._cycle_lock.hold() as acquired:
            if not acquired:
                self._logger.info("auto_refresh.cycle_skipped_lock_held")
                return AutoRefreshCycleReport(ran=False)
            return self._run_locked_cycle()

    def _run_locked_cycle(self) -> AutoRefreshCycleReport:
        now = self._clock()
        with self._unit_of_work_factory() as uow:
            settings = uow.get_settings()
            if not settings.enabled:
                return AutoRefreshCycleReport(ran=True, enabled=False)
            watched = uow.list_watched_event_sports(now)
            refresh_times = uow.get_sport_refresh_times()

        candidates = self._sport_keys_for(watched)
        due = self._cadence_engine.due_sports(
            candidates, refresh_times, settings.interval_minutes, now
        )
        report = AutoRefreshCycleReport(ran=True, enabled=True, candidate_sports=sorted(candidates))
        if due and self._paused(settings.interval_minutes, now):
            return report.model_copy(update={"paused": True})

        outcomes: list[AutoRefreshOutcome] = []
        for sport in due:
            outcome, out_of_credits = self._refresh(sport)
            outcomes.append(outcome)
            if out_of_credits:
                # The rest would be refused too; the next poll is paused.
                break
        return report.model_copy(update={"refreshed": outcomes})

    def _paused(self, interval_minutes: int, now: datetime) -> bool:
        """Out of credits: stay on, spend nothing, and check the balance for free
        at most once per interval until credits are back (ADR-016)."""
        quota = self._quota_service.status()
        if not quota.paused or quota.latest is None:
            return False
        last_seen = quota.latest.observed_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        if last_seen + timedelta(minutes=interval_minutes) > now:
            return True
        try:
            self._quote_ingestion_service.check_quota()
        except Exception:
            self._logger.exception("auto_refresh.balance_check_failed")
            return True
        still_paused = self._quota_service.status().paused
        self._logger.info("auto_refresh.balance_checked", extra={"paused": still_paused})
        return still_paused

    def _sport_keys_for(self, watched: list[EventSport]) -> set[str]:
        """Provider keys for stored (sport, league) pairs; never a guessed key."""
        if not watched:
            # No watch to serve: skip even the catalog lookup.
            return set()
        wanted = {(event_sport.sport, event_sport.league) for event_sport in watched}
        return {
            entry.key
            for entry in self._quote_ingestion_service.list_supported_sports()
            if (entry.sport, entry.league) in wanted
        }

    def _refresh(self, sport: str) -> tuple[AutoRefreshOutcome, bool]:
        started_at = perf_counter()
        error: Exception | None = None
        events_refreshed = 0
        try:
            # Ingestion writes the refresh record; the status endpoint reads it back.
            refreshed = self._quote_ingestion_service.refresh_sport(
                sport, trigger=RefreshTrigger.AUTO
            )
            events_refreshed = len(refreshed.summaries)
        except OutOfUsageCreditsError as refused:
            self._logger.warning("auto_refresh.out_of_credits", extra={"sport": sport})
            error = refused
        except Exception as failed:
            # Logged and reported; the next poll carries on regardless.
            self._logger.exception("auto_refresh.refresh_failed", extra={"sport": sport})
            error = failed

        result = RefreshResult.from_error(error)
        outcome = AutoRefreshOutcome(
            sport=sport,
            status=result.outcome,
            at=self._clock(),
            events_refreshed=events_refreshed,
            error=result.error,
        )
        self._logger.info(
            "auto_refresh.refreshed",
            extra={
                "sport": sport,
                "status": outcome.status.value,
                "events_refreshed": outcome.events_refreshed,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return outcome, result.outcome is RefreshOutcomeStatus.REFUSED
