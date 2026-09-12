from datetime import UTC, datetime, timedelta

from backend.app.domain.models import MarketType, Quote

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
