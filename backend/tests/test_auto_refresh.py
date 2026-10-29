import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, update

from backend.app.application.auto_refresh_service import AutoRefreshService
from backend.app.application.quote_ingestion_service import QuoteIngestionService
from backend.app.config import Settings
from backend.app.domain.auto_refresh import AutoRefreshSettings, RefreshOutcomeStatus
from backend.app.domain.models import ProviderFetchReport, Quote
from backend.app.engines.auto_refresh_cadence_engine import AutoRefreshCadenceEngine
from backend.app.engines.normalization_engine import NormalizationEngine
from backend.app.infrastructure.persistence.auto_refresh_uow import (
    PostgresAdvisoryCycleLock,
    SqlAlchemyAutoRefreshUnitOfWork,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.quote_ingestion_uow import (
    SqlAlchemyQuoteIngestionUnitOfWork,
)
from backend.app.infrastructure.persistence.schema import events_table, watch_intents_table
from backend.app.infrastructure.publishers.in_memory_publisher import (
    InMemoryWorkflowEventPublisher,
)
from backend.app.infrastructure.quote_provider import FIXTURE_EVENT_ID, InMemoryQuoteProvider
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database

# The fixture provider keys its one sport on the stored sport name.
FIXTURE_SPORT_KEY = "basketball"
T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


# --- cadence rule (pure) ---------------------------------------------------


def test_a_sport_never_pulled_sport_wide_is_due() -> None:
    due = AutoRefreshCadenceEngine().due_sports(["basketball"], {}, 5, T0)

    assert due == ["basketball"]


def test_a_sport_is_due_once_a_full_interval_has_passed_and_not_before() -> None:
    engine = AutoRefreshCadenceEngine()
    last = {"basketball": T0}

    assert engine.due_sports(["basketball"], last, 5, T0 + timedelta(minutes=4, seconds=59)) == []
    assert engine.due_sports(["basketball"], last, 5, T0 + timedelta(minutes=5)) == [
        "basketball"
    ]


def test_each_sport_runs_on_its_own_cooldown() -> None:
    last = {"basketball": T0, "icehockey_nhl": T0 - timedelta(minutes=10)}

    due = AutoRefreshCadenceEngine().due_sports(
        ["icehockey_nhl", "basketball", "icehockey_nhl"], last, 5, T0 + timedelta(minutes=1)
    )

    assert due == ["icehockey_nhl"]


# --- worker cycle against a migrated database ----------------------------------


class CountingProvider(InMemoryQuoteProvider):
    """Fixture provider that counts sport-wide pulls and can be made to fail."""

    def __init__(self) -> None:
        super().__init__()
        self.sport_fetches: list[str] = []
        self.catalog_reads = 0
        self.fail_with: Exception | None = None

    def list_quotes_for_sport(
        self, sport: str
    ) -> tuple[dict[str, list[Quote]], ProviderFetchReport]:
        self.sport_fetches.append(sport)
        if self.fail_with is not None:
            raise self.fail_with
        return super().list_quotes_for_sport(sport)

    def list_supported_sports(self):  # type: ignore[no-untyped-def]
        self.catalog_reads += 1
        return super().list_supported_sports()


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class LockHeldElsewhere:
    @contextmanager
    def hold(self) -> Iterator[bool]:
        yield False


class Harness:
    def __init__(self, database_url: str, *, drop_existing: bool = False) -> None:
        self.session_factory = prepare_test_database(
            database_url, seed_demo=True, drop_existing=drop_existing
        )
        self.provider = CountingProvider()
        # Real now, not T0: the seeded event starts three days from the real clock.
        self.clock = Clock(datetime.now(UTC))
        self.ingestion = QuoteIngestionService(
            unit_of_work_factory=lambda: SqlAlchemyQuoteIngestionUnitOfWork(
                self.session_factory
            ),
            quote_provider=self.provider,
            normalization_engine=NormalizationEngine(),
            workflow_event_publisher=InMemoryWorkflowEventPublisher(),
        )
        self.service = self.build_service(PostgresAdvisoryCycleLock(self.session_factory))

    def build_service(self, lock: object) -> AutoRefreshService:
        return AutoRefreshService(
            unit_of_work_factory=lambda: SqlAlchemyAutoRefreshUnitOfWork(self.session_factory),
            cycle_lock=lock,  # type: ignore[arg-type]
            quote_ingestion_service=self.ingestion,
            cadence_engine=AutoRefreshCadenceEngine(),
            clock=self.clock,
        )

    def switch(self, enabled: bool, interval_minutes: int = 5) -> None:
        self.service.update_settings(
            AutoRefreshSettings(enabled=enabled, interval_minutes=interval_minutes)
        )

    def add_watch(self, *, expires_at: datetime | None = None) -> None:
        with self.session_factory.create_session() as session:
            session.execute(
                insert(watch_intents_table).values(
                    id=str(uuid4()),
                    event_external_id=FIXTURE_EVENT_ID,
                    market_type="moneyline",
                    selection="knicks",
                    line=None,
                    # Out of reach, so evaluation after a refresh never retires it.
                    target_price=900,
                    expires_at=expires_at,
                    status="active",
                )
            )
            session.commit()

    def start_event(self) -> None:
        with self.session_factory.create_session() as session:
            session.execute(
                update(events_table)
                .where(events_table.c.external_id == FIXTURE_EVENT_ID)
                .values(starts_at=self.clock.now - timedelta(minutes=1))
            )
            session.commit()

    def close(self) -> None:
        self.session_factory.engine.dispose()


@pytest.fixture
def harness(sqlite_database_url: str) -> Iterator[Harness]:
    built = Harness(sqlite_database_url)
    yield built
    built.close()


def test_with_the_switch_off_a_cycle_never_contacts_the_provider(harness: Harness) -> None:
    harness.add_watch()

    report = harness.service.run_cycle()

    assert (report.ran, report.enabled) == (True, False)
    assert harness.provider.sport_fetches == []


def test_with_no_qualifying_watch_a_cycle_makes_no_upstream_call(harness: Harness) -> None:
    harness.switch(True)

    report = harness.service.run_cycle()

    assert report.candidate_sports == []
    assert harness.provider.sport_fetches == []
    assert harness.provider.catalog_reads == 0


def test_watches_the_evaluator_would_skip_do_not_qualify(harness: Harness) -> None:
    harness.switch(True)
    harness.add_watch(expires_at=harness.clock.now - timedelta(minutes=1))

    assert harness.service.run_cycle().candidate_sports == []

    harness.add_watch()
    harness.start_event()

    assert harness.service.run_cycle().candidate_sports == []
    assert harness.provider.sport_fetches == []


def test_a_watched_sport_refreshes_once_per_interval(harness: Harness) -> None:
    harness.switch(True, interval_minutes=5)
    harness.add_watch()

    first = harness.service.run_cycle()
    harness.clock.now += timedelta(minutes=4)
    second = harness.service.run_cycle()
    harness.clock.now += timedelta(minutes=2)
    third = harness.service.run_cycle()

    assert [len(r.refreshed) for r in (first, second, third)] == [1, 0, 1]
    assert harness.provider.sport_fetches == [FIXTURE_SPORT_KEY, FIXTURE_SPORT_KEY]
    outcome = harness.service.get_status().last_outcome
    assert outcome is not None
    assert (outcome.sport, outcome.status, outcome.events_refreshed) == (
        FIXTURE_SPORT_KEY,
        RefreshOutcomeStatus.SUCCEEDED,
        1,
    )


def test_a_manual_sport_wide_refresh_resets_the_cooldown(harness: Harness) -> None:
    harness.switch(True)
    harness.add_watch()

    harness.ingestion.refresh_sport(FIXTURE_SPORT_KEY)
    report = harness.service.run_cycle()

    assert report.candidate_sports == [FIXTURE_SPORT_KEY]
    assert report.refreshed == []
    assert harness.provider.sport_fetches == [FIXTURE_SPORT_KEY]


def test_a_per_event_refresh_leaves_the_cooldown_alone(harness: Harness) -> None:
    harness.switch(True)
    harness.add_watch()

    harness.ingestion.refresh_quotes(FIXTURE_EVENT_ID)
    report = harness.service.run_cycle()

    assert len(report.refreshed) == 1


def test_a_failed_refresh_is_reported_and_the_next_poll_carries_on(harness: Harness) -> None:
    harness.switch(True)
    harness.add_watch()
    harness.provider.fail_with = RuntimeError("upstream 500")

    failed = harness.service.run_cycle()
    harness.provider.fail_with = None
    recovered = harness.service.run_cycle()

    assert failed.refreshed[0].status is RefreshOutcomeStatus.FAILED
    assert failed.refreshed[0].error == "upstream 500"
    # A failed pull never stamped the sport, so it is due again straight away.
    assert recovered.refreshed[0].status is RefreshOutcomeStatus.SUCCEEDED


def test_a_cycle_is_skipped_while_another_worker_holds_the_lock(harness: Harness) -> None:
    harness.switch(True)
    harness.add_watch()

    report = harness.build_service(LockHeldElsewhere()).run_cycle()

    assert report.ran is False
    assert harness.provider.sport_fetches == []


def test_recording_an_outcome_never_flips_the_switch(harness: Harness) -> None:
    harness.switch(True, interval_minutes=7)
    harness.add_watch()

    harness.service.run_cycle()

    settings = harness.service.get_status().settings
    assert (settings.enabled, settings.interval_minutes) == (True, 7)


# --- API ---------------------------------------------------------------------


def _client(database_url: str) -> TestClient:
    return TestClient(create_app(Settings(database_url_override=database_url)))


def test_auto_refresh_defaults_to_off_every_five_minutes(sqlite_database_url: str) -> None:
    prepare_test_database(sqlite_database_url, seed_demo=False)

    response = _client(sqlite_database_url).get("/auto-refresh")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "interval_minutes": 5,
        "quota_floor": None,
        "last_outcome": None,
    }


def test_settings_survive_a_restart(sqlite_database_url: str) -> None:
    prepare_test_database(sqlite_database_url, seed_demo=False)

    put = _client(sqlite_database_url).put(
        "/auto-refresh", json={"enabled": True, "interval_minutes": 15}
    )
    # A fresh app over the same database stands in for a restarted API.
    reread = _client(sqlite_database_url).get("/auto-refresh")

    assert put.status_code == 200
    assert reread.json()["enabled"] is True
    assert reread.json()["interval_minutes"] == 15


@pytest.mark.parametrize("interval", [0, 61])
def test_interval_outside_one_to_sixty_is_rejected(
    sqlite_database_url: str, interval: int
) -> None:
    prepare_test_database(sqlite_database_url, seed_demo=False)
    client = _client(sqlite_database_url)

    response = client.put("/auto-refresh", json={"enabled": True, "interval_minutes": interval})

    assert response.status_code == 422
    assert client.get("/auto-refresh").json()["enabled"] is False


def test_turning_the_switch_on_does_not_refresh_from_the_api(sqlite_database_url: str) -> None:
    prepare_test_database(sqlite_database_url, seed_demo=True)
    client = _client(sqlite_database_url)

    client.put("/auto-refresh", json={"enabled": True, "interval_minutes": 5})

    assert client.get("/auto-refresh").json()["last_outcome"] is None


# --- Postgres ----------------------------------------------------------------


def _postgres_url() -> str:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")
    return database_url


def test_postgres_cooldown_rule_and_persisted_settings() -> None:
    built = Harness(_postgres_url(), drop_existing=True)
    try:
        built.switch(True, interval_minutes=5)
        built.add_watch()

        first = built.service.run_cycle()
        second = built.service.run_cycle()
        # Past the interval, not on it: ingestion stamps the real clock, a moment
        # after the test clock's start.
        built.clock.now += timedelta(minutes=6)
        third = built.service.run_cycle()

        assert [len(r.refreshed) for r in (first, second, third)] == [1, 0, 1]
        with SqlAlchemyAutoRefreshUnitOfWork(built.session_factory) as uow:
            assert uow.get_settings().enabled is True
            assert FIXTURE_SPORT_KEY in uow.get_sport_refresh_times()
    finally:
        built.close()


def test_postgres_advisory_lock_admits_one_cycle_at_a_time() -> None:
    session_factory = prepare_test_database(_postgres_url(), seed_demo=False, drop_existing=True)
    other_factory = DatabaseSessionFactory(_postgres_url())
    try:
        first = PostgresAdvisoryCycleLock(session_factory)
        second = PostgresAdvisoryCycleLock(other_factory)

        with first.hold() as held:
            with second.hold() as also_held:
                assert (held, also_held) == (True, False)
        with second.hold() as after_release:
            assert after_release is True
    finally:
        other_factory.engine.dispose()
        session_factory.engine.dispose()
