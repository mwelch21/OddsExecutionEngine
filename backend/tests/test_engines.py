from backend.app.domain.models import MarketType, OrderIntent, Quote
from backend.app.engines.price_comparison_engine import compare_prices, is_price_fillable
from backend.app.engines.quote_matching_engine import match_quotes
from backend.app.engines.recommendation_engine import generate_recommendation, rank_quotes


def test_match_quotes_filters_moneyline_selection() -> None:
    intent = OrderIntent(
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )
    quotes = [
        Quote("event-1", "BookA", MarketType.MONEYLINE, "knicks", 120),
        Quote("event-1", "BookB", MarketType.MONEYLINE, "celtics", -140),
        Quote("event-2", "BookC", MarketType.MONEYLINE, "knicks", 125),
    ]

    assert match_quotes(intent, quotes) == [quotes[0]]


def test_match_quotes_requires_exact_line_for_spread_and_total() -> None:
    intent = OrderIntent(
        event_id="event-1",
        market_type=MarketType.SPREAD,
        selection="knicks",
        line=5.5,
        target_price=-110,
    )
    quotes = [
        Quote("event-1", "BookA", MarketType.SPREAD, "knicks", -108, 5.5),
        Quote("event-1", "BookB", MarketType.SPREAD, "knicks", -105, 4.5),
    ]

    assert match_quotes(intent, quotes) == [quotes[0]]


def test_is_price_fillable_treats_higher_american_price_as_better() -> None:
    assert is_price_fillable(120, 110) is True
    assert is_price_fillable(-105, -110) is True
    assert is_price_fillable(-115, -110) is False


def test_compare_prices_orders_american_prices_for_bettor() -> None:
    assert compare_prices(120, 110) == 1
    assert compare_prices(-105, -110) == 1
    assert compare_prices(-115, -110) == -1
    assert compare_prices(-110, -110) == 0


def test_rank_quotes_uses_price_then_sportsbook_name() -> None:
    quotes = [
        Quote("event-1", "FanDuel", MarketType.MONEYLINE, "knicks", 125),
        Quote("event-1", "DraftKings", MarketType.MONEYLINE, "knicks", 125),
        Quote("event-1", "BetMGM", MarketType.MONEYLINE, "knicks", 120),
    ]

    ranked = rank_quotes(quotes)

    assert [quote.sportsbook for quote in ranked] == ["DraftKings", "FanDuel", "BetMGM"]


def test_generate_recommendation_returns_nearest_miss_when_unfillable() -> None:
    intent = OrderIntent(
        event_id="event-1",
        market_type=MarketType.TOTAL,
        selection="over",
        line=221.5,
        target_price=-105,
    )
    quotes = [
        Quote("event-1", "BookA", MarketType.TOTAL, "over", -108, 221.5),
        Quote("event-1", "BookB", MarketType.TOTAL, "over", -112, 221.5),
    ]

    recommendation = generate_recommendation(intent, quotes)

    assert recommendation.fillable is False
    assert recommendation.best_quote == quotes[0]
    assert recommendation.nearest_miss == quotes[0]
    assert [quote.sportsbook for quote in recommendation.ranked_quotes] == ["BookA", "BookB"]


def test_generate_recommendation_handles_no_matches() -> None:
    intent = OrderIntent(
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )

    recommendation = generate_recommendation(intent, [])

    assert recommendation.fillable is False
    assert recommendation.best_quote is None
    assert recommendation.nearest_miss is None
    assert recommendation.ranked_quotes == []
    assert recommendation.matched_quote_count == 0
