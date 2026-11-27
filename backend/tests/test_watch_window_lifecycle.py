"""Watch windows across the event lifecycle (#10, ADR-017).

Runs the real ingestion and watch services against a migrated database, with a
provider whose feed the test controls. No upstream is ever contacted.
"""

import os
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update

from backend.app.application.quote_ingestion_service import QuoteIngestionService
from backend.app.application.watch_intent_service import (
    WatchIntentAlreadyExpiredError,
)
from backend.app.config import Settings
from backend.app.domain.models import (
    EventStatus,
    ExpiredReason,
    LinePhase,
    MarketType,
    WatchIntent,
    WatchStatus,
    WatchWindow,
)
from backend.app.domain.watch_window import WatchWindowNotAllowedError
from backend.app.engines.normalization_engine import NormalizationEngine
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.quote_ingestion_uow import (
    SqlAlchemyQuoteIngestionUnitOfWork,
)
from backend.app.infrastructure.persistence.schema import (
    events_table,
    public_events_table,
    watch_intents_table,
    workflow_events_table,
)
from backend.app.infrastructure.publishers.in_memory_publisher import (
    InMemoryWorkflowEventPublisher,
)
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database
from backend.tests.test_event_lifecycle import (
    MOVED_LIVE,
    MOVED_PRE_GAME,
    NOW,
    SPORT_KEY,
    Harness,
    _quote,
)

EVENT_ID = "tip-off"
BEFORE = NOW + timedelta(hours=1)
STARTED = NOW - timedelta(minutes=5)


class WindowHarness(Harness):
    def watch(
        self, target_price: int, window: WatchWindow | None = None, event_id: str = EVENT_ID
    ) -> WatchIntent:
        return self.watches.create_watch_intent(
            event_id=event_id,
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            target_price=target_price,
            window=window,
        ).watch_intent

    def stored(self, watch_id: str) -> tuple[WatchStatus, ExpiredReason | None]:
        with self.session_factory.create_session() as session:
            row = session.execute(
                select(watch_intents_table.c.status, watch_intents_table.c.expired_reason)
                .where(watch_intents_table.c.id == watch_id)
            ).one()
        reason = None if row.expired_reason is None else ExpiredReason(row.expired_reason)
        return WatchStatus(row.status), reason

    def expired_events(self) -> list[dict[str, object]]:
        with self.session_factory.create_session() as session:
            payloads = session.execute(
                select(workflow_events_table.c.payload).where(
                    workflow_events_table.c.event_type == "WatchIntentExpired"
                )
            ).scalars()
            return [dict(payload) for payload in payloads]

    def public_event_types(self) -> list[str]:
        with self.session_factory.create_session() as session:
            return list(session.execute(select(public_events_table.c.type)).scalars())

    def public_opportunity_phases(self) -> list[str]:
        with self.session_factory.create_session() as session:
            payloads = session.execute(select(public_events_table.c.payload)).scalars()
            return [payload["data"]["phase"] for payload in payloads]

    def pre_game(self, price: int, sportsbook: str = "DraftKings") -> None:
        self.provider.offer(
            EVENT_ID, BEFORE, [_quote(EVENT_ID, sportsbook, price, MOVED_PRE_GAME)]
        )
        self.ingestion.refresh_sport(SPORT_KEY)

    def live(self, price: int, sportsbook: str = "FanDuel") -> None:
        self.provider.offer(EVENT_ID, STARTED, [_quote(EVENT_ID, sportsbook, price, MOVED_LIVE)])
        self.ingestion.refresh_sport(SPORT_KEY)

    def end(self) -> None:
        self.provider.withdraw(EVENT_ID)
        self.ingestion.refresh_sport(SPORT_KEY)

    def ingestion_only(self) -> QuoteIngestionService:
        """Ingestion with no watch evaluation after it, so any expiry seen is the
        ingestion pass's own."""
        return QuoteIngestionService(
            unit_of_work_factory=lambda: SqlAlchemyQuoteIngestionUnitOfWork(
                self.session_factory
            ),
            quote_provider=self.provider,
            normalization_engine=NormalizationEngine(),
            workflow_event_publisher=InMemoryWorkflowEventPublisher(),
            clock=lambda: self.now,
        )

    def ttl_due_watch(self) -> WatchIntent:
        watch = self.watch(400)
        with self.session_factory.create_session() as session:
            session.execute(
                update(watch_intents_table)
                .where(watch_intents_table.c.id == watch.id)
                .values(expires_at=self.now - timedelta(minutes=1))
            )
            session.commit()
        return watch

    def set_event(self, **values: object) -> None:
        with self.session_factory.create_session() as session:
            session.execute(
                update(events_table).where(events_table.c.external_id == EVENT_ID).values(**values)
            )
            session.commit()


@pytest.fixture(params=["sqlite", "postgres"])
def harness(request: pytest.FixtureRequest, sqlite_database_url: str) -> WindowHarness:
    if request.param == "sqlite":
        return WindowHarness(prepare_test_database(sqlite_database_url, seed_demo=False))
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")
    return WindowHarness(
        prepare_test_database(database_url, seed_demo=False, drop_existing=True)
    )


def test_the_default_window_comes_from_the_event_status(harness: WindowHarness) -> None:
    harness.pre_game(110)
    assert harness.watch(400).window is WatchWindow.PRE_GAME

    harness.live(110)
    assert harness.watch(400).window is WatchWindow.LIVE


def test_a_pre_game_watch_ignores_live_lines_and_expires_when_the_event_starts(
    harness: WindowHarness,
) -> None:
    harness.pre_game(110)
    watch = harness.watch(140)

    # Kickoff with a live line that meets the target: it never fills a pre-game watch.
    harness.live(150)

    assert harness.watches.list_opportunities(EVENT_ID) == []
    assert harness.stored(watch.id) == (WatchStatus.EXPIRED, ExpiredReason.EVENT_STARTED)
    [expired] = harness.expired_events()
    assert expired["watch_intent_id"] == watch.id
    assert expired["window"] == "pre_game"
    assert expired["expired_reason"] == "event_started"
    # Lifecycle expiry is visible, never pushed.
    assert harness.public_event_types() == []
    assert harness.watches.list_watch_intents(status=WatchStatus.EXPIRED) == [
        watch.model_copy(
            update={"status": WatchStatus.EXPIRED, "expired_reason": ExpiredReason.EVENT_STARTED}
        )
    ]


def test_a_live_watch_ignores_pre_game_lines_and_fills_on_a_live_one(
    harness: WindowHarness,
) -> None:
    harness.pre_game(110)
    watch = harness.watch(140, WatchWindow.LIVE)

    # A pre-game line meets the target: a live watch does not take it.
    harness.pre_game(150)
    assert harness.watches.list_opportunities(EVENT_ID) == []
    assert harness.stored(watch.id) == (WatchStatus.ACTIVE, None)

    harness.live(145)

    [found] = harness.watches.list_opportunities(EVENT_ID)
    assert found.opportunity.best_sportsbook == "FanDuel"
    assert found.opportunity.phase is LinePhase.LIVE
    assert harness.stored(watch.id) == (WatchStatus.TRIGGERED, None)
    assert harness.public_opportunity_phases() == ["live"]


def test_a_full_game_watch_fills_on_either_phase(harness: WindowHarness) -> None:
    harness.pre_game(110)
    before = harness.watch(140, WatchWindow.FULL_GAME)
    during = harness.watch(160, WatchWindow.FULL_GAME)

    harness.pre_game(150)
    harness.live(165)

    phases = {
        found.opportunity.watch_intent_id: found.opportunity.phase
        for found in harness.watches.list_opportunities(EVENT_ID)
    }
    assert phases == {before.id: LinePhase.PRE_GAME, during.id: LinePhase.LIVE}
    assert sorted(harness.public_opportunity_phases()) == ["live", "pre_game"]


def test_every_active_watch_expires_when_its_event_ends(harness: WindowHarness) -> None:
    harness.pre_game(110)
    full_game = harness.watch(400, WatchWindow.FULL_GAME)
    harness.live(110)
    live = harness.watch(400)

    harness.end()

    assert harness.status(EVENT_ID) is EventStatus.ENDED
    assert harness.stored(full_game.id) == (WatchStatus.EXPIRED, ExpiredReason.EVENT_ENDED)
    assert harness.stored(live.id) == (WatchStatus.EXPIRED, ExpiredReason.EVENT_ENDED)
    assert sorted(str(e["expired_reason"]) for e in harness.expired_events()) == [
        "event_ended",
        "event_ended",
    ]
    assert harness.public_event_types() == []


def test_a_per_event_refresh_that_finds_the_event_gone_expires_its_watches(
    harness: WindowHarness,
) -> None:
    harness.live(110)
    watch = harness.watch(400)

    harness.provider.withdraw(EVENT_ID)
    harness.ingestion.refresh_quotes(EVENT_ID)

    assert harness.stored(watch.id) == (WatchStatus.EXPIRED, ExpiredReason.EVENT_ENDED)


def test_a_stale_observation_closes_no_window(harness: WindowHarness) -> None:
    harness.provider.answered_at = NOW
    harness.pre_game(110)
    watch = harness.watch(400)

    # An older answer that saw the event live lands late: status is not written,
    # so the pre-game watch stays armed.
    harness.provider.answered_at = NOW - timedelta(minutes=10)
    harness.live(110)

    assert harness.status(EVENT_ID) is EventStatus.UPCOMING
    assert harness.stored(watch.id) == (WatchStatus.ACTIVE, None)


def test_evaluation_expires_a_watch_whose_window_closed_without_ingestion(
    harness: WindowHarness,
) -> None:
    harness.pre_game(110)
    watch = harness.watch(400)
    # Status written by something other than this ingestion path: the backstop
    # in evaluation still retires the watch.
    with harness.session_factory.create_session() as session:
        session.execute(
            update(events_table)
            .where(events_table.c.external_id == EVENT_ID)
            .values(status=EventStatus.LIVE.value)
        )
        session.commit()

    assert harness.watches.evaluate_for_event(EVENT_ID) == []
    assert harness.stored(watch.id) == (WatchStatus.EXPIRED, ExpiredReason.EVENT_STARTED)


def test_no_watch_can_be_made_on_an_ended_event(harness: WindowHarness) -> None:
    harness.live(110)
    harness.end()

    with pytest.raises(WatchWindowNotAllowedError):
        harness.watch(400)
    with harness.session_factory.create_session() as session:
        assert session.execute(select(watch_intents_table.c.id)).first() is None


def test_ttl_expiry_records_ttl(harness: WindowHarness) -> None:
    harness.pre_game(110)
    watch = harness.watches.create_watch_intent(
        event_id=EVENT_ID,
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=400,
        expires_at=datetime.now(UTC) + timedelta(milliseconds=1),
    ).watch_intent
    harness.now = datetime.now(UTC) + timedelta(seconds=1)

    harness.pre_game(110)

    assert harness.stored(watch.id) == (WatchStatus.EXPIRED, ExpiredReason.TTL)


# --- API ------------------------------------------------------------------------

SEEDED_EVENT_ID = "nba-knicks-celtics-2026-04-11"


def _client(database_url: str) -> TestClient:
    prepare_test_database(database_url, seed_demo=True)
    return TestClient(create_app(Settings(database_url_override=database_url)))


def _set_status(database_url: str, status: EventStatus) -> None:
    with DatabaseSessionFactory(database_url).create_session() as session:
        session.execute(
            update(events_table)
            .where(events_table.c.external_id == SEEDED_EVENT_ID)
            .values(status=status.value)
        )
        session.commit()


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_id": SEEDED_EVENT_ID,
        "market_type": "moneyline",
        "selection": "knicks",
        "target_price": 400,
    }
    payload.update(overrides)
    return payload


def test_the_api_shows_the_window_and_takes_one_when_asked(sqlite_database_url: str) -> None:
    with _client(sqlite_database_url) as client:
        defaulted = client.post("/api/v1/watch-intents", json=_payload())
        chosen = client.post("/api/v1/watch-intents", json=_payload(window="full_game"))
        listed = client.get("/api/v1/watch-intents").json()["watch_intents"]

    assert defaulted.status_code == 201
    assert defaulted.json()["window"] == "pre_game"
    assert defaulted.json()["expired_reason"] is None
    assert chosen.json()["window"] == "full_game"
    assert {w["window"] for w in listed} == {"pre_game", "full_game"}


def test_the_api_refuses_a_watch_on_an_ended_event(sqlite_database_url: str) -> None:
    with _client(sqlite_database_url) as client:
        _set_status(sqlite_database_url, EventStatus.ENDED)
        response = client.post("/api/v1/watch-intents", json=_payload())

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EVENT_ENDED"


def test_the_api_refuses_a_pre_game_watch_on_a_live_event(sqlite_database_url: str) -> None:
    with _client(sqlite_database_url) as client:
        _set_status(sqlite_database_url, EventStatus.LIVE)
        refused = client.post("/api/v1/watch-intents", json=_payload(window="pre_game"))
        defaulted = client.post("/api/v1/watch-intents", json=_payload())

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "WINDOW_CLOSED"
    assert defaulted.json()["window"] == "live"


def test_the_api_rejects_an_unknown_window(sqlite_database_url: str) -> None:
    with _client(sqlite_database_url) as client:
        response = client.post("/api/v1/watch-intents", json=_payload(window="halftime"))

    assert response.status_code == 422


def test_the_api_shows_why_a_watch_expired(sqlite_database_url: str) -> None:
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    with _client(sqlite_database_url) as client:
        started = client.post("/api/v1/watch-intents", json=_payload()).json()
        _expire_as_started(sqlite_database_url, started["id"])
        lapsed = client.post("/api/v1/watch-intents", json=_payload(expires_at=past)).json()
        fetched = client.get(f"/api/v1/watch-intents/{started['id']}").json()
        expired = client.get("/api/v1/watch-intents", params={"status": "expired"}).json()

    assert fetched["status"] == "expired"
    assert fetched["expired_reason"] == "event_started"
    # A TTL that passed before any evaluation reads as expired, with its reason.
    assert {w["id"]: w["expired_reason"] for w in expired["watch_intents"]} == {
        started["id"]: "event_started",
        lapsed["id"]: "ttl",
    }


def _expire_as_started(database_url: str, watch_id: str) -> None:
    with DatabaseSessionFactory(database_url).create_session() as session:
        session.execute(
            update(watch_intents_table)
            .where(watch_intents_table.c.id == watch_id)
            .values(status="expired", expired_reason="event_started")
        )
        session.commit()


# --- Review round 1 -------------------------------------------------------------


def test_a_stale_offered_answer_expires_nothing_not_even_a_due_ttl(
    harness: WindowHarness,
) -> None:
    harness.provider.answered_at = NOW
    harness.pre_game(110)
    watch = harness.ttl_due_watch()

    harness.provider.answered_at = NOW - timedelta(minutes=10)
    harness.provider.offer(EVENT_ID, STARTED, [_quote(EVENT_ID, "FanDuel", 110, MOVED_LIVE)])
    harness.ingestion_only().refresh_sport(SPORT_KEY)
    harness.ingestion_only().refresh_quotes(EVENT_ID)

    assert harness.status(EVENT_ID) is EventStatus.UPCOMING
    assert harness.stored(watch.id) == (WatchStatus.ACTIVE, None)
    assert harness.expired_events() == []


def test_a_stale_absent_answer_expires_nothing_not_even_a_due_ttl(
    harness: WindowHarness,
) -> None:
    harness.provider.answered_at = NOW
    harness.live(110)
    watch = harness.ttl_due_watch()

    # An older pull that no longer offers the event: it may not end it.
    harness.provider.answered_at = NOW - timedelta(minutes=10)
    harness.provider.withdraw(EVENT_ID)
    harness.ingestion_only().refresh_sport(SPORT_KEY)
    harness.ingestion_only().refresh_quotes(EVENT_ID)

    assert harness.status(EVENT_ID) is EventStatus.LIVE
    assert harness.stored(watch.id) == (WatchStatus.ACTIVE, None)
    assert harness.expired_events() == []


def test_a_fresh_answer_does_expire_a_due_ttl_in_the_ingestion_pass(
    harness: WindowHarness,
) -> None:
    harness.provider.answered_at = NOW
    harness.pre_game(110)
    watch = harness.ttl_due_watch()

    harness.provider.answered_at = NOW + timedelta(seconds=1)
    harness.ingestion_only().refresh_sport(SPORT_KEY)

    assert harness.stored(watch.id) == (WatchStatus.EXPIRED, ExpiredReason.TTL)


def test_the_backstop_expires_a_pre_game_watch_once_an_unobserved_kickoff_passes(
    harness: WindowHarness,
) -> None:
    harness.pre_game(110)
    pre_game = harness.watch(400)
    live = harness.watch(400, WatchWindow.LIVE)
    # Kickoff passed with no refresh since: still stored upcoming.
    harness.set_event(starts_at=NOW - timedelta(minutes=1))

    assert harness.watches.evaluate_for_event(EVENT_ID) == []

    assert harness.stored(pre_game.id) == (WatchStatus.EXPIRED, ExpiredReason.EVENT_STARTED)
    # A live window is still open: the next refresh may find the event live.
    assert harness.stored(live.id) == (WatchStatus.ACTIVE, None)
    # The stored status is left as observed (ADR-019).
    assert harness.status(EVENT_ID) is EventStatus.UPCOMING


def test_an_expired_watch_cannot_be_cancelled(harness: WindowHarness) -> None:
    harness.pre_game(110)
    watch = harness.watch(400)
    harness.live(110)
    assert harness.stored(watch.id) == (WatchStatus.EXPIRED, ExpiredReason.EVENT_STARTED)

    with pytest.raises(WatchIntentAlreadyExpiredError):
        harness.watches.cancel_watch_intent(watch.id)

    assert harness.stored(watch.id) == (WatchStatus.EXPIRED, ExpiredReason.EVENT_STARTED)


def test_a_watch_past_its_ttl_cancels_as_expired(harness: WindowHarness) -> None:
    harness.pre_game(110)
    watch = harness.watch(400)
    with harness.session_factory.create_session() as session:
        session.execute(
            update(watch_intents_table)
            .where(watch_intents_table.c.id == watch.id)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        session.commit()

    with pytest.raises(WatchIntentAlreadyExpiredError):
        harness.watches.cancel_watch_intent(watch.id)
    assert harness.stored(watch.id) == (WatchStatus.ACTIVE, None)


def test_the_api_answers_409_when_cancelling_an_expired_watch(
    sqlite_database_url: str,
) -> None:
    with _client(sqlite_database_url) as client:
        created = client.post("/api/v1/watch-intents", json=_payload()).json()
        _expire_as_started(sqlite_database_url, created["id"])
        response = client.delete(f"/api/v1/watch-intents/{created['id']}")
        fetched = client.get(f"/api/v1/watch-intents/{created['id']}").json()

    assert response.status_code == 409
    assert fetched["status"] == "expired"
    assert fetched["expired_reason"] == "event_started"


def _postgres_harness() -> WindowHarness:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")
    return WindowHarness(prepare_test_database(database_url, seed_demo=False, drop_existing=True))


def test_postgres_creation_waits_for_an_uncommitted_status_write() -> None:
    """The race from review round 1: a status write in flight when a watch is made.

    Ingestion's status write holds the event row until it commits. Creation reads
    the event FOR UPDATE, so it waits, then reads the committed status and picks
    the window from it. Without the lock it would read `upcoming`, default to
    `pre_game`, and land an armed pre-game watch on a live event after the
    expiry scan had already run.
    """
    harness = _postgres_harness()
    harness.pre_game(110)

    created: list[WatchIntent] = []
    errors: list[BaseException] = []

    def create() -> None:
        try:
            created.append(harness.watch(400))
        except BaseException as error:  # noqa: BLE001 - surfaced by the assert below
            errors.append(error)

    with harness.session_factory.create_session() as in_flight:
        in_flight.execute(
            update(events_table)
            .where(events_table.c.external_id == EVENT_ID)
            .values(status=EventStatus.LIVE.value)
        )
        creator = threading.Thread(target=create)
        creator.start()
        creator.join(timeout=1.0)
        assert creator.is_alive(), "creation did not wait for the status write"
        in_flight.commit()
    creator.join(timeout=10.0)

    assert errors == []
    [watch] = created
    assert watch.window is WatchWindow.LIVE


def test_postgres_a_status_write_waits_for_a_watch_being_created() -> None:
    """The other order: the watch commits first, and the expiry scan sees it."""
    harness = _postgres_harness()
    harness.pre_game(110)

    watch_id = "wi-racing"
    with harness.session_factory.create_session() as creating:
        # What creation does: lock the event, then insert, then commit.
        creating.execute(
            select(events_table.c.status)
            .where(events_table.c.external_id == EVENT_ID)
            .with_for_update()
        )
        creating.execute(
            insert(watch_intents_table).values(
                id=watch_id,
                event_external_id=EVENT_ID,
                market_type="moneyline",
                selection="knicks",
                target_price=400,
                status="active",
                watch_window="pre_game",
            )
        )
        writer = threading.Thread(target=lambda: harness.live(110))
        writer.start()
        writer.join(timeout=1.0)
        assert writer.is_alive(), "the status write did not wait for the creator"
        creating.commit()
    writer.join(timeout=10.0)
    assert not writer.is_alive()

    assert harness.status(EVENT_ID) is EventStatus.LIVE
    assert harness.stored(watch_id) == (WatchStatus.EXPIRED, ExpiredReason.EVENT_STARTED)
