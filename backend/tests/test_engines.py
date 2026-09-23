from datetime import UTC, datetime, timedelta

from backend.app.domain.models import (
    MarketType,
    MatchingQuote,
    Opportunity,
    OrderIntent,
    Quote,
    WatchIntent,
    WatchStatus,
)
from backend.app.engines.normalization_engine import NormalizationEngine
from backend.app.engines.opportunity_validity_engine import OpportunityValidityEngine
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine

normalization_engine = NormalizationEngine()
price_comparison_service = PriceComparisonService()
quote_matching_engine = QuoteMatchingEngine()
recommendation_engine = RecommendationEngine(price_comparison_service)
watch_evaluation_engine = WatchEvaluationEngine(
    price_comparison_service, recommendation_engine
)
opportunity_validity_engine = OpportunityValidityEngine()
MarketLookup = dict[tuple[str, str, str, float | None], str]


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


# ── WatchEvaluationEngine ─────────────────────────────────────────────


def test_watch_evaluation_creates_opportunities_for_fillable_quotes() -> None:
    intents = [
        WatchIntent(
            id="wi-1",
            event_id="event-1",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            target_price=120,
        ),
    ]
    quotes = [
        Quote(
            event_id="event-1",
            sportsbook="BookA",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=125,
        ),
        Quote(
            event_id="event-1",
            sportsbook="BookB",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=122,
        ),
    ]
    lookup: MarketLookup = {("event-1", "moneyline", "knicks", None): "market-1"}

    opportunities = watch_evaluation_engine.evaluate(intents, quotes, lookup)

    assert len(opportunities) == 1
    assert opportunities[0].best_sportsbook == "BookA"
    assert opportunities[0].best_price == 125
    assert opportunities[0].watch_intent_id == "wi-1"
    # BookB is fillable too and rides along in the snapshot rather than becoming
    # a second opportunity.
    assert [(q.sportsbook, q.price) for q in opportunities[0].matching_quotes] == [
        ("BookA", 125),
        ("BookB", 122),
    ]


def test_watch_evaluation_returns_empty_when_no_fillable_quotes() -> None:
    intents = [
        WatchIntent(
            id="wi-1",
            event_id="event-1",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            target_price=130,
        ),
    ]
    quotes = [
        Quote(
            event_id="event-1",
            sportsbook="BookA",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=125,
        ),
    ]
    lookup: MarketLookup = {("event-1", "moneyline", "knicks", None): "market-1"}

    opportunities = watch_evaluation_engine.evaluate(intents, quotes, lookup)

    assert opportunities == []


def test_watch_evaluation_excludes_books_that_miss_the_target() -> None:
    intents = [
        WatchIntent(
            id="wi-1",
            event_id="event-1",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            target_price=120,
        ),
    ]
    quotes = [
        Quote(
            event_id="event-1",
            sportsbook="BookA",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=125,
        ),
        Quote(
            event_id="event-1",
            sportsbook="BookB",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=110,
        ),
    ]
    lookup: MarketLookup = {("event-1", "moneyline", "knicks", None): "market-1"}

    opportunities = watch_evaluation_engine.evaluate(intents, quotes, lookup)

    assert [q.sportsbook for q in opportunities[0].matching_quotes] == ["BookA"]


def test_watch_evaluation_breaks_price_ties_alphabetically() -> None:
    intents = [
        WatchIntent(
            id="wi-1",
            event_id="event-1",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            target_price=120,
        ),
    ]
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
    ]
    lookup: MarketLookup = {("event-1", "moneyline", "knicks", None): "market-1"}

    opportunities = watch_evaluation_engine.evaluate(intents, quotes, lookup)

    assert len(opportunities) == 1
    assert opportunities[0].best_sportsbook == "DraftKings"
    assert [q.sportsbook for q in opportunities[0].matching_quotes] == [
        "DraftKings",
        "FanDuel",
    ]


def test_watch_evaluation_skips_triggered_intents() -> None:
    intents = [
        WatchIntent(
            id="wi-1",
            event_id="event-1",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            target_price=120,
            status=WatchStatus.TRIGGERED,
        ),
    ]
    quotes = [
        Quote(
            event_id="event-1",
            sportsbook="BookA",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=125,
        ),
    ]
    lookup: MarketLookup = {("event-1", "moneyline", "knicks", None): "market-1"}

    opportunities = watch_evaluation_engine.evaluate(intents, quotes, lookup)

    assert opportunities == []


def test_watch_evaluation_matches_on_line() -> None:
    intents = [
        WatchIntent(
            id="wi-1",
            event_id="event-1",
            market_type=MarketType.SPREAD,
            selection="knicks",
            target_price=-110,
            line=5.5,
        ),
    ]
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
    lookup: MarketLookup = {
        ("event-1", "spread", "knicks", 5.5): "market-1",
        ("event-1", "spread", "knicks", 4.5): "market-2",
    }

    opportunities = watch_evaluation_engine.evaluate(intents, quotes, lookup)

    assert len(opportunities) == 1
    assert opportunities[0].best_sportsbook == "BookA"
    assert opportunities[0].line == 5.5


def test_watch_evaluation_skips_cancelled_intents() -> None:
    intents = [
        WatchIntent(
            id="wi-1",
            event_id="event-1",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            target_price=120,
            status=WatchStatus.CANCELLED,
        ),
    ]
    quotes = [
        Quote(
            event_id="event-1",
            sportsbook="BookA",
            market_type=MarketType.MONEYLINE,
            selection="knicks",
            price=125,
        ),
    ]
    lookup: MarketLookup = {("event-1", "moneyline", "knicks", None): "market-1"}

    opportunities = watch_evaluation_engine.evaluate(intents, quotes, lookup)

    assert opportunities == []


# ── OpportunityValidityEngine ──────────────────────────────────────────


def _make_opportunity(created_at: datetime) -> Opportunity:
    return Opportunity(
        id="opp-1",
        watch_intent_id="wi-1",
        event_id="event-1",
        market_id="market-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
        best_sportsbook="BookA",
        best_price=125,
        matching_quotes=[MatchingQuote(sportsbook="BookA", price=125)],
        created_at=created_at,
    )


def test_opportunity_valid_within_ttl_and_no_newer_quote() -> None:
    now = datetime.now(UTC)
    opp = _make_opportunity(now - timedelta(minutes=2))
    quote_time = now - timedelta(minutes=3)

    result = opportunity_validity_engine.check_validity(opp, quote_time, ttl_minutes=5, now=now)

    assert result.is_valid is True
    assert result.reason is None


def test_opportunity_invalid_when_expired() -> None:
    now = datetime.now(UTC)
    opp = _make_opportunity(now - timedelta(minutes=10))
    quote_time = now - timedelta(minutes=11)

    result = opportunity_validity_engine.check_validity(opp, quote_time, ttl_minutes=5, now=now)

    assert result.is_valid is False
    assert result.reason == "expired"


def test_opportunity_invalid_when_quote_superseded() -> None:
    now = datetime.now(UTC)
    opp = _make_opportunity(now - timedelta(minutes=2))
    quote_time = now - timedelta(minutes=1)

    result = opportunity_validity_engine.check_validity(opp, quote_time, ttl_minutes=5, now=now)

    assert result.is_valid is False
    assert result.reason == "quote_superseded"


def test_opportunity_invalid_when_quote_removed() -> None:
    now = datetime.now(UTC)
    opp = _make_opportunity(now - timedelta(minutes=2))

    result = opportunity_validity_engine.check_validity(opp, None, ttl_minutes=5, now=now)

    assert result.is_valid is False
    assert result.reason == "quote_removed"


def test_opportunity_validity_batch_handles_mixed_results() -> None:
    now = datetime.now(UTC)
    valid_opp = _make_opportunity(now - timedelta(minutes=2))
    expired_opp = Opportunity(
        id="opp-2",
        watch_intent_id="wi-1",
        event_id="event-1",
        market_id="market-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
        best_sportsbook="BookB",
        best_price=122,
        matching_quotes=[MatchingQuote(sportsbook="BookB", price=122)],
        created_at=now - timedelta(minutes=10),
    )

    items: list[tuple[Opportunity, datetime | None]] = [
        (valid_opp, now - timedelta(minutes=3)),
        (expired_opp, now - timedelta(minutes=11)),
    ]

    results = opportunity_validity_engine.check_validity_batch(items, ttl_minutes=5, now=now)

    assert len(results) == 2
    assert results[0].is_valid is True
    assert results[1].is_valid is False
