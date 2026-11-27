"""Watch window rules (ADR-017): the default policy, what a window admits, and
when it closes. Pure: no database."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.domain.models import (
    EventLifecycle,
    EventStatus,
    ExpiredReason,
    LinePhase,
    MarketType,
    Quote,
    WatchIntent,
    WatchStatus,
    WatchWindow,
)
from backend.app.domain.watch_window import (
    WatchWindowNotAllowedError,
    WatchWindowPolicy,
    WatchWindowRefusal,
)
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine
from backend.app.engines.watch_window_engine import WatchWindowEngine

NOW = datetime(2026, 11, 27, 20, 0, tzinfo=UTC)
POLICY = WatchWindowPolicy()
ENGINE = WatchWindowEngine()


def _lifecycle(status: EventStatus) -> EventLifecycle:
    return EventLifecycle(status=status, starts_at=NOW - timedelta(minutes=5))


def _watch(
    window: WatchWindow,
    *,
    expires_at: datetime | None = None,
    status: WatchStatus = WatchStatus.ACTIVE,
) -> WatchIntent:
    return WatchIntent(
        id=f"wi-{window.value}",
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
        window=window,
        expires_at=expires_at,
        status=status,
    )


# --- Default policy -------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [(EventStatus.UPCOMING, WatchWindow.PRE_GAME), (EventStatus.LIVE, WatchWindow.LIVE)],
)
def test_the_default_window_follows_the_event_status(
    status: EventStatus, expected: WatchWindow
) -> None:
    assert POLICY.default_for(status) is expected
    assert POLICY.resolve(None, _lifecycle(status)) is expected


def test_an_event_never_stored_defaults_to_pre_game() -> None:
    assert POLICY.resolve(None, None) is WatchWindow.PRE_GAME


def test_an_upcoming_event_past_its_start_still_defaults_to_pre_game() -> None:
    # Not observed since kickoff: the start time alone never makes an event live.
    assert POLICY.resolve(None, _lifecycle(EventStatus.UPCOMING)) is WatchWindow.PRE_GAME


@pytest.mark.parametrize("window", list(WatchWindow))
def test_an_asked_for_window_is_kept_on_an_upcoming_event(window: WatchWindow) -> None:
    assert POLICY.resolve(window, _lifecycle(EventStatus.UPCOMING)) is window


@pytest.mark.parametrize("window", [WatchWindow.LIVE, WatchWindow.FULL_GAME])
def test_a_live_event_takes_any_window_that_is_still_open(window: WatchWindow) -> None:
    assert POLICY.resolve(window, _lifecycle(EventStatus.LIVE)) is window


def test_a_pre_game_watch_on_a_live_event_is_refused() -> None:
    with pytest.raises(WatchWindowNotAllowedError) as refused:
        POLICY.resolve(WatchWindow.PRE_GAME, _lifecycle(EventStatus.LIVE))
    assert refused.value.refusal is WatchWindowRefusal.WINDOW_CLOSED


@pytest.mark.parametrize("window", [None, *WatchWindow])
def test_no_watch_can_be_made_on_an_ended_event(window: WatchWindow | None) -> None:
    with pytest.raises(WatchWindowNotAllowedError) as refused:
        POLICY.resolve(window, _lifecycle(EventStatus.ENDED))
    assert refused.value.refusal is WatchWindowRefusal.EVENT_ENDED


# --- What a window admits -------------------------------------------------------


@pytest.mark.parametrize(
    ("window", "phase", "admitted"),
    [
        (WatchWindow.PRE_GAME, LinePhase.PRE_GAME, True),
        (WatchWindow.PRE_GAME, LinePhase.LIVE, False),
        (WatchWindow.PRE_GAME, None, True),
        (WatchWindow.LIVE, LinePhase.PRE_GAME, False),
        (WatchWindow.LIVE, LinePhase.LIVE, True),
        (WatchWindow.LIVE, None, False),
        (WatchWindow.FULL_GAME, LinePhase.PRE_GAME, True),
        (WatchWindow.FULL_GAME, LinePhase.LIVE, True),
    ],
)
def test_a_window_admits_only_its_own_lines(
    window: WatchWindow, phase: LinePhase | None, admitted: bool
) -> None:
    assert ENGINE.admits(window, phase) is admitted


# --- When a window closes -------------------------------------------------------


@pytest.mark.parametrize(
    ("window", "status", "reason"),
    [
        (WatchWindow.PRE_GAME, EventStatus.UPCOMING, None),
        (WatchWindow.PRE_GAME, EventStatus.LIVE, ExpiredReason.EVENT_STARTED),
        (WatchWindow.PRE_GAME, EventStatus.ENDED, ExpiredReason.EVENT_ENDED),
        (WatchWindow.LIVE, EventStatus.UPCOMING, None),
        (WatchWindow.LIVE, EventStatus.LIVE, None),
        (WatchWindow.LIVE, EventStatus.ENDED, ExpiredReason.EVENT_ENDED),
        (WatchWindow.FULL_GAME, EventStatus.UPCOMING, None),
        (WatchWindow.FULL_GAME, EventStatus.LIVE, None),
        (WatchWindow.FULL_GAME, EventStatus.ENDED, ExpiredReason.EVENT_ENDED),
    ],
)
def test_status_closes_a_window(
    window: WatchWindow, status: EventStatus, reason: ExpiredReason | None
) -> None:
    assert ENGINE.lifecycle_expiry(window, status) is reason


def test_a_passed_ttl_is_the_reason_even_once_the_event_ended() -> None:
    watch = _watch(WatchWindow.LIVE, expires_at=NOW - timedelta(hours=1))
    assert ENGINE.expiry_reason(watch, EventStatus.ENDED, NOW) is ExpiredReason.TTL


def test_an_event_never_stored_closes_only_on_ttl() -> None:
    assert ENGINE.expiry_reason(_watch(WatchWindow.PRE_GAME), None, NOW) is None
    expired = _watch(WatchWindow.PRE_GAME, expires_at=NOW)
    assert ENGINE.expiry_reason(expired, None, NOW) is ExpiredReason.TTL


def test_a_watch_that_is_no_longer_active_never_expires_again() -> None:
    triggered = _watch(WatchWindow.PRE_GAME, status=WatchStatus.TRIGGERED)
    assert ENGINE.expiry_reason(triggered, EventStatus.ENDED, NOW) is None


def test_expiry_reasons_names_only_the_watches_that_close() -> None:
    watches = [_watch(window) for window in WatchWindow]
    reasons = ENGINE.expiry_reasons(watches, {"event-1": EventStatus.LIVE}, NOW)
    assert reasons == {"wi-pre_game": ExpiredReason.EVENT_STARTED}


def test_a_ttl_read_projection_says_why_it_expired() -> None:
    watch = _watch(WatchWindow.PRE_GAME, expires_at=NOW - timedelta(seconds=1))
    projected = watch.with_effective_status(NOW)
    assert projected.status is WatchStatus.EXPIRED
    assert projected.expired_reason is ExpiredReason.TTL


# --- Evaluation honours the window ----------------------------------------------


def _quote(sportsbook: str, price: int, phase: LinePhase) -> Quote:
    return Quote(
        event_id="event-1",
        sportsbook=sportsbook,
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        price=price,
        phase=phase,
    )


def _evaluate(window: WatchWindow, quotes: list[Quote]) -> list[tuple[str, LinePhase]]:
    comparison = PriceComparisonService()
    engine = WatchEvaluationEngine(comparison, RecommendationEngine(comparison), ENGINE)
    opportunities = engine.evaluate(
        [_watch(window)], quotes, {("event-1", "moneyline", "knicks", None): "market-1"}
    )
    return [(opp.best_sportsbook, opp.phase) for opp in opportunities]


QUOTES = [
    _quote("DraftKings", 150, LinePhase.PRE_GAME),
    _quote("FanDuel", 130, LinePhase.LIVE),
]


def test_a_pre_game_watch_fills_on_the_pre_game_line_only() -> None:
    assert _evaluate(WatchWindow.PRE_GAME, QUOTES) == [("DraftKings", LinePhase.PRE_GAME)]
    assert _evaluate(WatchWindow.PRE_GAME, QUOTES[1:]) == []


def test_a_live_watch_ignores_a_better_pre_game_line() -> None:
    assert _evaluate(WatchWindow.LIVE, QUOTES) == [("FanDuel", LinePhase.LIVE)]
    assert _evaluate(WatchWindow.LIVE, QUOTES[:1]) == []


def test_a_full_game_watch_fills_on_either_and_reports_the_best_line_phase() -> None:
    assert _evaluate(WatchWindow.FULL_GAME, QUOTES) == [("DraftKings", LinePhase.PRE_GAME)]
    assert _evaluate(WatchWindow.FULL_GAME, QUOTES[1:]) == [("FanDuel", LinePhase.LIVE)]
