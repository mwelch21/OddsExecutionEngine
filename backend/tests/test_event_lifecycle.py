"""Event status from feed presence, line phase, and what a watch may fill (#38).

Runs the real ingestion and watch services against a migrated database, with a
provider whose feed the test controls. No upstream is ever contacted.
"""

import logging
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from backend.app.application.quote_ingestion_service import QuoteIngestionService
from backend.app.application.watch_intent_service import WatchIntentService
from backend.app.domain.models import (
    EventInfo,
    EventParticipant,
    EventStatus,
    LinePhase,
    MarketType,
    ProviderFetchReport,
    Quote,
    SupportedSport,
)
from backend.app.engines.normalization_engine import NormalizationEngine
from backend.app.engines.opportunity_validity_engine import OpportunityValidityEngine
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.event_read_uow import (
    SqlAlchemyEventReadUnitOfWork,
)
from backend.app.infrastructure.persistence.quote_ingestion_uow import (
    SqlAlchemyQuoteIngestionUnitOfWork,
)
from backend.app.infrastructure.persistence.schema import (
    events_table,
    market_quotes_history_table,
)
from backend.app.infrastructure.persistence.watch_intent_uow import (
    SqlAlchemyWatchIntentUnitOfWork,
)
from backend.app.infrastructure.publishers.in_memory_publisher import (
    InMemoryWorkflowEventPublisher,
)
from backend.tests.db_helpers import prepare_test_database

SPORT_KEY = "basketball_nba"
NOW = datetime.now(UTC)
MOVED_PRE_GAME = NOW - timedelta(hours=6)
MOVED_LIVE = NOW - timedelta(seconds=30)


class ControlledFeedProvider:
    """A feed whose offered events and quotes the test sets between pulls."""

    def __init__(self) -> None:
        self.events: dict[str, EventInfo] = {}
        self.quotes: dict[str, list[Quote]] = {}

    def offer(self, event_id: str, starts_at: datetime, quotes: list[Quote]) -> None:
        self.events[event_id] = EventInfo(
            id=event_id,
            sport="basketball",
            league="NBA",
            commence_time=starts_at,
            participants=[
                EventParticipant(name="Celtics", side="home", sort_order=1),
                EventParticipant(name="Knicks", side="away", sort_order=2),
            ],
        )
        self.quotes[event_id] = quotes

    def withdraw(self, event_id: str) -> None:
        self.quotes.pop(event_id, None)

    def list_quotes(
        self, event_id: str, sport: str
    ) -> tuple[list[Quote], ProviderFetchReport]:
        offered = event_id in self.quotes
        return self.quotes.get(event_id, []), ProviderFetchReport(
            upstream_contacted=True, data_age_seconds=0.0, event_offered=offered
        )

    def list_quotes_for_sport(
        self, sport: str
    ) -> tuple[dict[str, list[Quote]], ProviderFetchReport]:
        return dict(self.quotes), ProviderFetchReport(
            upstream_contacted=True, data_age_seconds=0.0
        )

    def get_event_info(self, event_id: str) -> EventInfo | None:
        return self.events.get(event_id)

    def check_quota(self) -> None:
        pass

    def list_supported_sports(self) -> list[SupportedSport]:
        return [SupportedSport(key=SPORT_KEY, sport="basketball", league="NBA")]


def _quote(
    event_id: str, sportsbook: str, price: int, quoted_at: datetime | None
) -> Quote:
    return Quote(
        event_id=event_id,
        sportsbook=sportsbook,
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        price=price,
        quoted_at=quoted_at,
    )


class Harness:
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self.session_factory = session_factory
        self.provider = ControlledFeedProvider()
        comparison = PriceComparisonService()
        recommendation = RecommendationEngine(comparison)
        self.watches = WatchIntentService(
            unit_of_work_factory=lambda: SqlAlchemyWatchIntentUnitOfWork(session_factory),
            workflow_event_publisher=InMemoryWorkflowEventPublisher(),
            watch_evaluation_engine=WatchEvaluationEngine(comparison, recommendation),
            opportunity_validity_engine=OpportunityValidityEngine(),
            opportunity_ttl_minutes=15,
        )
        self.ingestion = QuoteIngestionService(
            unit_of_work_factory=lambda: SqlAlchemyQuoteIngestionUnitOfWork(session_factory),
            quote_provider=self.provider,
            normalization_engine=NormalizationEngine(),
            workflow_event_publisher=InMemoryWorkflowEventPublisher(),
            watch_intent_service=self.watches,
        )

    def status(self, event_id: str) -> EventStatus:
        with self.session_factory.create_session() as session:
            value = session.execute(
                select(events_table.c.status).where(events_table.c.external_id == event_id)
            ).scalar_one()
        return EventStatus(value)

    def board_phases(self, event_id: str) -> dict[str, LinePhase | None]:
        with SqlAlchemyEventReadUnitOfWork(self.session_factory) as uow:
            markets = uow.list_market_quotes(event_id)
        return {q.sportsbook: q.phase for m in markets for q in m.quotes}

    def board_quotes(self, event_id: str) -> dict[str, Quote]:
        with SqlAlchemyEventReadUnitOfWork(self.session_factory) as uow:
            markets = uow.list_market_quotes(event_id)
        return {q.sportsbook: q for m in markets for q in m.quotes}


@pytest.fixture(params=["sqlite", "postgres"])
def harness(request: pytest.FixtureRequest, sqlite_database_url: str) -> Harness:
    if request.param == "sqlite":
        return Harness(prepare_test_database(sqlite_database_url, seed_demo=False))
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")
    return Harness(prepare_test_database(database_url, seed_demo=False, drop_existing=True))


def test_a_sport_pull_writes_upcoming_and_live_from_what_it_offers(harness: Harness) -> None:
    harness.provider.offer(
        "later", NOW + timedelta(days=1), [_quote("later", "DraftKings", 120, None)]
    )
    harness.provider.offer(
        "on-now", NOW - timedelta(hours=1), [_quote("on-now", "FanDuel", 130, MOVED_LIVE)]
    )

    harness.ingestion.refresh_sport(SPORT_KEY)

    assert harness.status("later") is EventStatus.UPCOMING
    assert harness.status("on-now") is EventStatus.LIVE
    assert harness.board_phases("later") == {"DraftKings": LinePhase.PRE_GAME}
    assert harness.board_phases("on-now") == {"FanDuel": LinePhase.LIVE}
    with harness.session_factory.create_session() as session:
        phases = set(session.execute(select(market_quotes_history_table.c.phase)).scalars())
    assert phases == {"pre_game", "live"}


def test_a_started_event_missing_from_the_next_pull_has_ended(harness: Harness) -> None:
    harness.provider.offer(
        "later", NOW + timedelta(days=1), [_quote("later", "DraftKings", 120, None)]
    )
    harness.provider.offer(
        "on-now", NOW - timedelta(hours=1), [_quote("on-now", "FanDuel", 130, None)]
    )
    harness.ingestion.refresh_sport(SPORT_KEY)

    harness.provider.withdraw("on-now")
    harness.provider.withdraw("later")
    harness.ingestion.refresh_sport(SPORT_KEY)

    assert harness.status("on-now") is EventStatus.ENDED
    # Absent before kickoff proves nothing: it stays upcoming.
    assert harness.status("later") is EventStatus.UPCOMING


def test_a_per_event_refresh_that_finds_no_event_reads_as_ended(harness: Harness) -> None:
    harness.provider.offer(
        "on-now", NOW - timedelta(hours=1), [_quote("on-now", "FanDuel", 130, None)]
    )
    harness.ingestion.refresh_sport(SPORT_KEY)
    harness.ingestion.refresh_quotes("on-now")
    assert harness.status("on-now") is EventStatus.LIVE

    harness.provider.withdraw("on-now")
    harness.ingestion.refresh_quotes("on-now")

    assert harness.status("on-now") is EventStatus.ENDED


def test_a_live_watch_fills_on_a_live_line_never_on_a_left_over_pre_game_one(
    harness: Harness,
) -> None:
    event_id = "tip-off"
    # Pre-game: DraftKings is at +150.
    harness.provider.offer(
        event_id, NOW + timedelta(hours=1), [_quote(event_id, "DraftKings", 150, MOVED_PRE_GAME)]
    )
    harness.ingestion.refresh_sport(SPORT_KEY)

    # Kickoff. DraftKings stops quoting; FanDuel quotes live at +130.
    harness.provider.offer(
        event_id, NOW - timedelta(minutes=5), [_quote(event_id, "FanDuel", 130, MOVED_LIVE)]
    )
    harness.ingestion.refresh_sport(SPORT_KEY)
    assert harness.status(event_id) is EventStatus.LIVE
    assert harness.board_phases(event_id) == {
        "DraftKings": LinePhase.PRE_GAME,
        "FanDuel": LinePhase.LIVE,
    }

    # +140 is met only by the left-over pre-game +150, which nobody can take now.
    created = harness.watches.create_watch_intent(
        event_id=event_id, market_type=MarketType.MONEYLINE, selection="knicks", target_price=140
    )
    assert created.opportunity is None

    # FanDuel moves live to +145: that one fills.
    harness.provider.offer(
        event_id, NOW - timedelta(minutes=5), [_quote(event_id, "FanDuel", 145, MOVED_LIVE)]
    )
    harness.ingestion.refresh_sport(SPORT_KEY)

    [opportunity] = harness.watches.list_opportunities(event_id)
    assert opportunity.opportunity.matching_quotes[0].sportsbook == "FanDuel"
    assert opportunity.opportunity.matching_quotes[0].price == 145


def test_an_ended_event_produces_nothing_and_says_why(
    harness: Harness, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Alembic's fileConfig disables loggers that existed before migrations ran.
    monkeypatch.setattr(WatchIntentService._logger, "disabled", False)
    event_id = "final-whistle"
    harness.provider.offer(
        event_id, NOW - timedelta(hours=2), [_quote(event_id, "FanDuel", 110, MOVED_LIVE)]
    )
    harness.ingestion.refresh_sport(SPORT_KEY)
    watch = harness.watches.create_watch_intent(
        event_id=event_id, market_type=MarketType.MONEYLINE, selection="knicks", target_price=200
    ).watch_intent
    assert [w.id for w in harness.watches.list_watch_intents()] == [watch.id]

    harness.provider.withdraw(event_id)
    harness.ingestion.refresh_sport(SPORT_KEY)

    with caplog.at_level(logging.INFO, logger="backend.app.application.watch_intent_service"):
        assert harness.watches.evaluate_for_event(event_id) == []
    skipped = [r for r in caplog.records if r.message == "watch_evaluation.skipped"]
    assert [getattr(r, "reason", None) for r in skipped] == ["event_ended"]
    # A watch on an ended event can no longer fill, so the default list drops it.
    assert harness.watches.list_watch_intents() == []


def test_both_clocks_keep_their_meaning_across_kickoff(harness: Harness) -> None:
    event_id = "clocks"
    harness.provider.offer(
        event_id, NOW + timedelta(hours=1), [_quote(event_id, "DraftKings", 150, MOVED_PRE_GAME)]
    )
    harness.ingestion.refresh_sport(SPORT_KEY)
    pre_game_pull = harness.board_quotes(event_id)["DraftKings"].ingested_at

    harness.provider.offer(
        event_id, NOW - timedelta(minutes=1), [_quote(event_id, "FanDuel", 130, None)]
    )
    harness.ingestion.refresh_sport(SPORT_KEY)
    board = harness.board_quotes(event_id)

    # The left-over pre-game row keeps its book time and its own pull time.
    assert board["DraftKings"].quoted_at == MOVED_PRE_GAME
    assert board["DraftKings"].ingested_at == pre_game_pull
    # A live line with no book time stays unknown age, never stamped "now".
    assert board["FanDuel"].quoted_at is None
    assert board["FanDuel"].line_age_known is False
    assert board["FanDuel"].ingested_at is not None
