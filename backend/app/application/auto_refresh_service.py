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
    CandidateSport,
    RefreshOutcomeStatus,
    UnknownSportKeysError,
    WatchedEvent,
)
from backend.app.domain.quota import OutOfUsageCreditsError
from backend.app.domain.refresh_records import RefreshResult, RefreshTrigger
from backend.app.engines.auto_refresh_cadence_engine import AutoRefreshCadenceEngine
from backend.app.engines.auto_refresh_candidate_engine import AutoRefreshCandidateEngine


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
        candidate_engine: AutoRefreshCandidateEngine,
        quota_service: QuotaService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._cycle_lock = cycle_lock
        self._quote_ingestion_service = quote_ingestion_service
        self._cadence_engine = cadence_engine
        self._candidate_engine = candidate_engine
        self._quota_service = quota_service
        self._clock = clock

    def get_status(self) -> AutoRefreshStatus:
        now = self._clock()
        with self._unit_of_work_factory() as uow:
            settings = uow.get_settings()
            last_outcome = uow.get_last_outcome()
            watched = uow.list_watched_events(now)
        return self._status(settings, last_outcome, watched, now)

    def update_settings(self, settings: AutoRefreshSettings) -> AutoRefreshStatus:
        """Replace the settings. Raises `UnknownSportKeysError`, and saves
        nothing, when the sport focus names a key outside the catalog."""
        self._assert_focus_in_catalog(settings.sport_focus)
        now = self._clock()
        with self._unit_of_work_factory() as uow:
            saved = uow.save_settings(settings)
            last_outcome = uow.get_last_outcome()
            watched = uow.list_watched_events(now)
        self._logger.info(
            "auto_refresh.settings_updated",
            extra={
                "enabled": saved.enabled,
                "interval_minutes": saved.interval_minutes,
                "live_interval_minutes": saved.live_interval_minutes,
                "sport_focus": list(saved.sport_focus),
            },
        )
        return self._status(saved, last_outcome, watched, now)

    def _status(
        self,
        settings: AutoRefreshSettings,
        last_outcome: AutoRefreshOutcome | None,
        watched: list[WatchedEvent],
        now: datetime,
    ) -> AutoRefreshStatus:
        # Stored watches and the local catalog only: no provider call.
        candidate_keys = self._sport_keys_for(self._candidate_engine.candidates(watched, now))
        focused = self._candidate_engine.focus(candidate_keys, settings.sport_focus)
        return AutoRefreshStatus(
            settings=settings,
            candidate_sports=sorted(candidate_keys),
            excluded_sports=focused.excluded,
            last_outcome=last_outcome,
            quota=self._quota_service.status(),
        )

    def _assert_focus_in_catalog(self, sport_focus: tuple[str, ...]) -> None:
        if not sport_focus:
            return
        supported = sorted(
            entry.key for entry in self._quote_ingestion_service.list_supported_sports()
        )
        unknown = [key for key in sport_focus if key not in supported]
        if unknown:
            raise UnknownSportKeysError(unknown, supported)

    def run_cycle(self) -> AutoRefreshCycleReport:
        """One poll: refresh every candidate sport whose cooldown has elapsed.

        Settings are read on every poll, so a changed interval applies from the
        next one with no restart.
        """
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
            watched = uow.list_watched_events(now)
            refresh_times = uow.get_sport_refresh_times()

        live_by_key = self._sport_keys_for(self._candidate_engine.candidates(watched, now))
        # The focus only narrows (#132): a sport outside it is dropped even with
        # qualifying watches; an empty focus keeps every candidate.
        focused = self._candidate_engine.focus(live_by_key, settings.sport_focus)
        candidates = set(focused.kept)
        live = {key for key in candidates if live_by_key[key]}
        due = self._cadence_engine.due_sports(
            candidates,
            live,
            refresh_times,
            settings.interval_minutes,
            settings.live_interval_minutes,
            now,
        )
        report = AutoRefreshCycleReport(
            ran=True,
            enabled=True,
            candidate_sports=sorted(candidates),
            live_sports=sorted(live),
            excluded_sports=focused.excluded,
        )
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

    def _sport_keys_for(self, candidates: list[CandidateSport]) -> dict[str, bool]:
        """Each candidate's provider key, True when it runs on the live interval.

        Keys come from stored (sport, league) pairs; never a guessed key.
        """
        if not candidates:
            # No watch to serve: skip even the catalog lookup.
            return {}
        live_by_pair = {
            (candidate.sport, candidate.league): candidate.live for candidate in candidates
        }
        return {
            entry.key: live_by_pair[(entry.sport, entry.league)]
            for entry in self._quote_ingestion_service.list_supported_sports()
            if (entry.sport, entry.league) in live_by_pair
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
