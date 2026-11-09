from datetime import UTC, datetime, timedelta

import pytest

from backend.app.domain.credits import BurnRow, RemainingReading
from backend.app.domain.quota import UpstreamCallKind
from backend.app.engines.credit_history_engine import CreditHistoryEngine, InvalidMonthError

engine = CreditHistoryEngine()
T0 = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def test_the_last_reading_in_an_hour_wins() -> None:
    readings = [
        RemainingReading(observed_at=T0 + timedelta(minutes=5), remaining=480),
        RemainingReading(observed_at=T0 + timedelta(minutes=50), remaining=477),
        RemainingReading(observed_at=T0 + timedelta(hours=1), remaining=474),
    ]

    points = engine.hourly(readings)

    assert [(p.hour, p.remaining) for p in points] == [(T0, 477), (T0 + timedelta(hours=1), 474)]


def test_thirty_days_is_at_most_720_hourly_buckets() -> None:
    since = engine.history_since(T0 + timedelta(minutes=30), days=30)

    assert since == T0 - timedelta(hours=719)


def test_december_ends_at_the_next_new_year() -> None:
    assert engine.month_window("2026-12") == (
        datetime(2026, 12, 1, tzinfo=UTC),
        datetime(2027, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize("month", ["2026-00", "2026-13", "26-01", ""])
def test_a_month_must_be_yyyy_mm(month: str) -> None:
    with pytest.raises(InvalidMonthError):
        engine.month_window(month)


def test_burn_sums_per_sport_and_per_kind_most_credits_first() -> None:
    rows = [
        BurnRow(sport_key="nba", kind=UpstreamCallKind.SPORT, credits=6, calls=2),
        BurnRow(sport_key="nba", kind=UpstreamCallKind.EVENT, credits=3, calls=1),
        BurnRow(sport_key="nhl", kind=UpstreamCallKind.SPORT, credits=12, calls=4),
        BurnRow(sport_key=None, kind=UpstreamCallKind.BALANCE_CHECK, credits=0, calls=2),
    ]

    burn = engine.burn("2026-11", rows)

    assert (burn.total_credits, burn.total_calls) == (21, 9)
    assert [(s.sport_key, s.credits, s.calls) for s in burn.by_sport] == [
        ("nhl", 12, 4),
        ("nba", 9, 3),
    ]
    assert [(k.kind, k.credits) for k in burn.by_kind] == [
        (UpstreamCallKind.SPORT, 18),
        (UpstreamCallKind.EVENT, 3),
        (UpstreamCallKind.BALANCE_CHECK, 0),
    ]
