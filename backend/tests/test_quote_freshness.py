from datetime import UTC, datetime, timedelta

from backend.app.domain.models import MarketType, Quote
from backend.app.infrastructure.quote_provider import build_fixture_quotes

INGESTED_AT = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)
MOVED_AT = INGESTED_AT - timedelta(days=3)


def _quote(**overrides: object) -> Quote:
    values: dict[str, object] = {
        "event_id": "event-1",
        "sportsbook": "DraftKings",
        "market_type": MarketType.MONEYLINE,
        "selection": "knicks",
        "price": 120,
    }
    values.update(overrides)
    return Quote(**values)  # type: ignore[arg-type]


def test_quote_reports_the_books_own_time_when_the_provider_supplies_it() -> None:
    quote = _quote(quoted_at=MOVED_AT, ingested_at=INGESTED_AT)

    assert quote.line_age_known is True
    assert quote.effective_quoted_at == MOVED_AT


def test_quote_without_a_provider_time_falls_back_to_ingest_time_as_unknown_age() -> None:
    quote = _quote(ingested_at=INGESTED_AT)

    assert quote.line_age_known is False
    assert quote.effective_quoted_at == INGESTED_AT


def test_quote_with_no_times_at_all_has_no_effective_time() -> None:
    quote = _quote()

    assert quote.line_age_known is False
    assert quote.effective_quoted_at is None


def test_demo_fixtures_cover_moved_stale_and_unknown_age() -> None:
    """The seeded stack must be able to show the difference the split exists for."""
    quotes = build_fixture_quotes()
    moneylines = {
        q.sportsbook: q for q in quotes if q.market_type is MarketType.MONEYLINE
    }
    now = datetime.now(UTC)

    just_moved = moneylines["DraftKings"]
    assert just_moved.line_age_known is True
    assert now - just_moved.quoted_at < timedelta(minutes=5)  # type: ignore[operator]

    stale = moneylines["BetMGM"]
    assert stale.line_age_known is True
    assert now - stale.quoted_at > timedelta(days=1)  # type: ignore[operator]

    assert any(not q.line_age_known for q in quotes)
