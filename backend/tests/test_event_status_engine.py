from datetime import UTC, datetime, timedelta

import pytest

from backend.app.domain.models import (
    EventLifecycle,
    EventListStatus,
    EventStatus,
    FillableSkipReason,
    LinePhase,
    MarketType,
    Quote,
)
from backend.app.engines.event_status_engine import EventStatusEngine

NOW = datetime(2026, 11, 27, 20, 0, tzinfo=UTC)
engine = EventStatusEngine()


def _quote(sportsbook: str, phase: LinePhase | None) -> Quote:
    return Quote(
        event_id="e1",
        sportsbook=sportsbook,
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        price=120,
        phase=phase,
    )


def test_an_offered_event_before_its_start_is_upcoming() -> None:
    assert engine.observe_offered(NOW + timedelta(minutes=1), NOW) is EventStatus.UPCOMING


def test_an_offered_event_with_no_known_start_is_upcoming() -> None:
    assert engine.observe_offered(None, NOW) is EventStatus.UPCOMING


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(hours=2)])
def test_an_offered_event_past_its_start_is_live(offset: timedelta) -> None:
    assert engine.observe_offered(NOW - offset, NOW) is EventStatus.LIVE


def test_a_naive_start_time_reads_as_utc() -> None:
    naive = (NOW - timedelta(minutes=5)).replace(tzinfo=None)
    assert engine.observe_offered(naive, NOW) is EventStatus.LIVE


def test_a_started_event_missing_from_a_sport_pull_has_ended() -> None:
    assert engine.observe_absent_from_sport_pull(NOW - timedelta(hours=3), NOW) is (
        EventStatus.ENDED
    )


@pytest.mark.parametrize("starts_at", [None, NOW + timedelta(hours=1)])
def test_an_unstarted_event_missing_from_a_sport_pull_is_left_alone(
    starts_at: datetime | None,
) -> None:
    # Absence before kickoff proves nothing: a book may simply not list it yet.
    assert engine.observe_absent_from_sport_pull(starts_at, NOW) is None


def test_an_event_refresh_that_finds_no_event_reads_as_ended() -> None:
    assert engine.observe_event_refresh(
        offered=False, starts_at=NOW + timedelta(days=1), now=NOW
    ) is EventStatus.ENDED


def test_an_event_refresh_that_finds_the_event_reads_its_start_time() -> None:
    assert engine.observe_event_refresh(
        offered=True, starts_at=NOW - timedelta(minutes=10), now=NOW
    ) is EventStatus.LIVE


@pytest.mark.parametrize(
    ("status", "phase"),
    [
        (EventStatus.UPCOMING, LinePhase.PRE_GAME),
        (EventStatus.LIVE, LinePhase.LIVE),
    ],
)
def test_a_line_takes_its_phase_from_the_event_status(
    status: EventStatus, phase: LinePhase
) -> None:
    assert engine.line_phase(status) is phase


def _at(status: EventStatus, starts_at: datetime | None = None) -> EventLifecycle:
    return EventLifecycle(status=status, starts_at=starts_at or NOW - timedelta(hours=1))


def test_a_started_event_not_observed_since_kickoff_fills_on_nothing() -> None:
    # Stored upcoming, start passed, no pull since: its pre-game lines may be gone.
    quotes = [_quote("DraftKings", LinePhase.PRE_GAME)]

    gate = engine.fillable_quotes(_at(EventStatus.UPCOMING), quotes, NOW)

    assert gate.quotes == []
    assert gate.skipped_reason is FillableSkipReason.EVENT_STATUS_UNOBSERVED


def test_an_ended_event_produces_nothing_and_says_why() -> None:
    quotes = [_quote("DraftKings", LinePhase.PRE_GAME), _quote("FanDuel", LinePhase.LIVE)]

    gate = engine.fillable_quotes(_at(EventStatus.ENDED), quotes, NOW)

    assert gate.quotes == []
    assert gate.skipped_reason is FillableSkipReason.EVENT_ENDED


def test_a_live_event_fills_only_on_live_lines() -> None:
    # A book that stopped quoting at kickoff keeps its pre-game row in latest; that
    # price cannot be had once the game is on.
    pre_game = _quote("DraftKings", LinePhase.PRE_GAME)
    live = _quote("FanDuel", LinePhase.LIVE)

    gate = engine.fillable_quotes(_at(EventStatus.LIVE), [pre_game, live], NOW)

    assert gate.quotes == [live]
    assert gate.skipped_reason is None


def test_an_upcoming_event_fills_on_every_stored_line() -> None:
    quotes = [_quote("DraftKings", LinePhase.PRE_GAME), _quote("FanDuel", None)]

    gate = engine.fillable_quotes(
        _at(EventStatus.UPCOMING, NOW + timedelta(hours=1)), quotes, NOW
    )

    assert gate.quotes == quotes
    assert gate.skipped_reason is None


def test_an_event_never_stored_is_treated_as_upcoming() -> None:
    quotes = [_quote("DraftKings", LinePhase.PRE_GAME)]
    assert engine.fillable_quotes(None, quotes, NOW).quotes == quotes


@pytest.mark.parametrize(
    ("status", "include_started", "expected"),
    [
        (None, None, EventListStatus.ALL),
        (None, True, EventListStatus.ALL),
        (None, False, EventListStatus.UPCOMING),
        (EventListStatus.LIVE, False, EventListStatus.LIVE),
    ],
)
def test_list_status_resolves_the_deprecated_alias_only_when_status_is_absent(
    status: EventListStatus | None, include_started: bool | None, expected: EventListStatus
) -> None:
    assert EventListStatus.resolve(status, include_started) is expected
