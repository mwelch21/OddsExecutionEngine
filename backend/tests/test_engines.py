from backend.app.domain.models import MarketType, OrderIntent, Quote
from backend.app.engines.normalization_engine import NormalizationEngine
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine

normalization_engine = NormalizationEngine()
price_comparison_service = PriceComparisonService()
quote_matching_engine = QuoteMatchingEngine()
recommendation_engine = RecommendationEngine(price_comparison_service)


def test_match_quotes_filters_moneyline_selection() -> None:
    intent = OrderIntent(
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )
    quotes = [
        Quote(
            event_id="event-1",
            sportsbook="BookA",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=120,
        ),
        Quote(
            event_id="event-1",
            sportsbook="BookB",
            market_type=MarketType.MONEYLINE,
            selection="celtics",
            price=-140,
        ),
        Quote(
            event_id="event-2",
            sportsbook="BookC",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=125,
        ),
    ]

    assert quote_matching_engine.match_quotes(intent, quotes) == [quotes[0]]


def test_match_quotes_requires_exact_line_for_spread_and_total() -> None:
    intent = OrderIntent(
        event_id="event-1",
        market_type=MarketType.SPREAD,
        selection="knicks",
        line=5.5,
        target_price=-110,
    )
    quotes = [
        Quote(
            event_id="event-1",
            sportsbook="BookA",
            market_type=MarketType.SPREAD,
            selection="knicks",
            price=-108,
            line=5.5,
        ),
        Quote(
            event_id="event-1",
            sportsbook="BookB",
            market_type=MarketType.SPREAD,
            selection="knicks",
            price=-105,
            line=4.5,
        ),
    ]

    assert quote_matching_engine.match_quotes(intent, quotes) == [quotes[0]]


def test_is_price_fillable_treats_higher_american_price_as_better() -> None:
    assert price_comparison_service.is_price_fillable(120, 110) is True
    assert price_comparison_service.is_price_fillable(-105, -110) is True
    assert price_comparison_service.is_price_fillable(-115, -110) is False


def test_compare_prices_orders_american_prices_for_bettor() -> None:
    assert price_comparison_service.compare_prices(120, 110) == 1
    assert price_comparison_service.compare_prices(-105, -110) == 1
    assert price_comparison_service.compare_prices(-115, -110) == -1
    assert price_comparison_service.compare_prices(-110, -110) == 0


def test_rank_quotes_uses_price_then_sportsbook_name() -> None:
    quotes = [
        Quote(
            event_id="event-1",
            sportsbook="FanDuel",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=125,
        ),
        Quote(
            event_id="event-1",
            sportsbook="DraftKings",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=125,
        ),
        Quote(
            event_id="event-1",
            sportsbook="BetMGM",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=120,
        ),
    ]

    ranked = recommendation_engine.rank_quotes(quotes)

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
        Quote(
            event_id="event-1",
            sportsbook="BookA",
            market_type=MarketType.TOTAL,
            selection="over",
            price=-108,
            line=221.5,
        ),
        Quote(
            event_id="event-1",
            sportsbook="BookB",
            market_type=MarketType.TOTAL,
            selection="over",
            price=-112,
            line=221.5,
        ),
    ]

    recommendation = recommendation_engine.generate_recommendation(intent, quotes)

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

    recommendation = recommendation_engine.generate_recommendation(intent, [])

    assert recommendation.fillable is False
    assert recommendation.best_quote is None
    assert recommendation.nearest_miss is None
    assert recommendation.ranked_quotes == []
    assert recommendation.matched_quote_count == 0


def test_normalization_engine_keeps_valid_quotes_for_target_event() -> None:
    quotes = [
        Quote(
            event_id="event-1",
            sportsbook="BookA",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=120,
        ),
        Quote(
            event_id="event-2",
            sportsbook="BookB",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=125,
        ),
    ]

    normalized = normalization_engine.normalize_quotes("event-1", quotes)

    assert normalized == [quotes[0]]


def test_normalization_engine_rejects_invalid_market_shape() -> None:
    quotes = [
        Quote(
            event_id="event-1",
            sportsbook="BookA",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=120,
            line=1.5,
        ),
        Quote(
            event_id="event-1",
            sportsbook="BookB",
            market_type=MarketType.TOTAL,
            selection="knicks",
            price=-110,
            line=221.5,
        ),
        Quote(
            event_id="event-1",
            sportsbook="BookC",
            market_type=MarketType.SPREAD,
            selection="knicks",
            price=-108,
        ),
    ]

    normalized = normalization_engine.normalize_quotes("event-1", quotes)

    assert normalized == []
