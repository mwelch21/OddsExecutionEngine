from datetime import UTC, datetime, timedelta

from backend.app.domain.models import (
    MarketType,
    Quote,
    WatchIntent,
    WatchStatus,
)
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine

NOW = datetime(2026, 4, 11, 12, 0, tzinfo=UTC)
EVENT_ID = "event-1"


def _build_engine() -> WatchEvaluationEngine:
    return WatchEvaluationEngine(
        quote_matching_engine=QuoteMatchingEngine(),
        recommendation_engine=RecommendationEngine(PriceComparisonService()),
        price_comparison_service=PriceComparisonService(),
    )


def _build_watch(
    *,
    watch_id: str = "watch-1",
    target_price: int = 120,
    market_type: MarketType = MarketType.MONEYLINE,
    selection: str = "knicks",
    line: float | None = None,
    expires_at: datetime | None = None,
) -> WatchIntent:
    return WatchIntent(
        id=watch_id,
        event_id=EVENT_ID,
        market_type=market_type,
        selection=selection,
        target_price=target_price,
        line=line,
        expires_at=expires_at,
        status=WatchStatus.ACTIVE,
        created_at=NOW - timedelta(hours=1),
    )


def _build_quote(
    *,
    sportsbook: str = "BookA",
    price: int = 125,
    market_type: MarketType = MarketType.MONEYLINE,
    selection: str = "knicks",
    line: float | None = None,
) -> Quote:
    return Quote(
        event_id=EVENT_ID,
        sportsbook=sportsbook,
        market_type=market_type,
        selection=selection,
        price=price,
        line=line,
    )


def test_watch_triggers_when_quote_meets_target_price() -> None:
    result = _build_engine().evaluate(
        [_build_watch(target_price=120)],
        [_build_quote(price=120)],
        now=NOW,
    )

    assert result.expired == []
    assert len(result.triggered) == 1
    assert result.triggered[0].watch_intent.id == "watch-1"
    assert result.triggered[0].quote.price == 120


def test_watch_does_not_trigger_when_quote_is_below_target_price() -> None:
    result = _build_engine().evaluate(
        [_build_watch(target_price=130)],
        [_build_quote(price=125)],
        now=NOW,
    )

    assert result.triggered == []
    assert result.expired == []


def test_triggering_quote_is_the_best_available_price() -> None:
    result = _build_engine().evaluate(
        [_build_watch(target_price=120)],
        [
            _build_quote(sportsbook="BookA", price=122),
            _build_quote(sportsbook="BookB", price=140),
            _build_quote(sportsbook="BookC", price=118),
        ],
        now=NOW,
    )

    assert result.triggered[0].quote.sportsbook == "BookB"
    assert result.triggered[0].quote.price == 140


def test_quotes_for_other_markets_do_not_trigger_a_watch() -> None:
    result = _build_engine().evaluate(
        [_build_watch(market_type=MarketType.SPREAD, selection="knicks", line=5.5)],
        [
            _build_quote(market_type=MarketType.MONEYLINE, price=200),
            _build_quote(market_type=MarketType.SPREAD, selection="celtics", line=5.5, price=200),
            _build_quote(market_type=MarketType.SPREAD, selection="knicks", line=4.5, price=200),
        ],
        now=NOW,
    )

    assert result.triggered == []


def test_expired_watches_are_separated_and_never_evaluated() -> None:
    expired_watch = _build_watch(
        watch_id="expired-watch",
        target_price=100,
        expires_at=NOW - timedelta(minutes=1),
    )

    result = _build_engine().evaluate(
        [expired_watch],
        [_build_quote(price=200)],
        now=NOW,
    )

    assert result.triggered == []
    assert [watch.id for watch in result.expired] == ["expired-watch"]


def test_watch_expiring_exactly_now_is_treated_as_expired() -> None:
    result = _build_engine().evaluate(
        [_build_watch(expires_at=NOW)],
        [_build_quote(price=200)],
        now=NOW,
    )

    assert result.triggered == []
    assert len(result.expired) == 1


def test_watch_with_future_expiry_still_evaluates() -> None:
    result = _build_engine().evaluate(
        [_build_watch(expires_at=NOW + timedelta(minutes=1))],
        [_build_quote(price=200)],
        now=NOW,
    )

    assert len(result.triggered) == 1
    assert result.expired == []


def test_multiple_watches_can_trigger_in_one_pass() -> None:
    result = _build_engine().evaluate(
        [
            _build_watch(watch_id="watch-1", target_price=120),
            _build_watch(watch_id="watch-2", target_price=125),
            _build_watch(watch_id="watch-3", target_price=200),
            _build_watch(watch_id="watch-4", expires_at=NOW - timedelta(seconds=1)),
        ],
        [_build_quote(price=125)],
        now=NOW,
    )

    assert [triggered.watch_intent.id for triggered in result.triggered] == ["watch-1", "watch-2"]
    assert [watch.id for watch in result.expired] == ["watch-4"]


def test_no_watches_produces_empty_result() -> None:
    result = _build_engine().evaluate([], [_build_quote()], now=NOW)

    assert result.triggered == []
    assert result.expired == []


def test_no_quotes_produces_no_triggers() -> None:
    result = _build_engine().evaluate([_build_watch()], [], now=NOW)

    assert result.triggered == []
    assert result.expired == []
