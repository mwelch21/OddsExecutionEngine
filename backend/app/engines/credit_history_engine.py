import re
from datetime import UTC, datetime, timedelta

from backend.app.domain.credits import (
    BurnRow,
    CreditBurn,
    KindBurn,
    QuotaHistoryPoint,
    RemainingReading,
    SportBurn,
)

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class InvalidMonthError(ValueError):
    def __init__(self, month: str) -> None:
        self.month = month
        super().__init__(f"Month must be YYYY-MM, got {month!r}.")


class CreditHistoryEngine:
    """Hourly balance buckets and monthly burn totals, from stored calls (#104).

    Pure: storage hands it readings and summed rows, the clock is the caller's.
    """

    def hourly(self, readings: list[RemainingReading]) -> list[QuotaHistoryPoint]:
        """The last remaining balance per UTC hour, oldest hour first.

        `readings` come in observation order, so a later one in the same hour wins.
        """
        last_by_hour: dict[datetime, int] = {}
        for reading in readings:
            hour = reading.observed_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
            last_by_hour[hour] = reading.remaining
        return [
            QuotaHistoryPoint(hour=hour, remaining=remaining)
            for hour, remaining in sorted(last_by_hour.items())
        ]

    def history_since(self, now: datetime, days: int) -> datetime:
        """The start of the window: `days` x 24 hourly buckets ending with this hour."""
        this_hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        return this_hour - timedelta(days=days) + timedelta(hours=1)

    def month_window(self, month: str) -> tuple[datetime, datetime]:
        """[start, end) of a `YYYY-MM` calendar month, in UTC."""
        match = _MONTH.match(month)
        if match is None:
            raise InvalidMonthError(month)
        year, number = int(match.group(1)), int(match.group(2))
        try:
            start = datetime(year, number, 1, tzinfo=UTC)
            end = datetime(year + number // 12, number % 12 + 1, 1, tzinfo=UTC)
        except ValueError as error:
            # Year 0000, or a 9999-12 whose end falls past the last datetime.
            raise InvalidMonthError(month) from error
        return start, end

    def month_of(self, now: datetime) -> str:
        return now.astimezone(UTC).strftime("%Y-%m")

    def burn(self, month: str, rows: list[BurnRow]) -> CreditBurn:
        """Totals per sport and per kind, most credits first. Each row is calls, so a
        call shared by coalesced refreshes was summed once before it got here."""
        starts_at, ends_at = self.month_window(month)
        by_sport: dict[str, SportBurn] = {}
        by_kind: dict[str, KindBurn] = {}
        for row in rows:
            if row.sport_key is not None:
                sport = by_sport.get(row.sport_key)
                by_sport[row.sport_key] = SportBurn(
                    sport_key=row.sport_key,
                    credits=row.credits + (sport.credits if sport else 0),
                    calls=row.calls + (sport.calls if sport else 0),
                )
            kind = by_kind.get(row.kind.value)
            by_kind[row.kind.value] = KindBurn(
                kind=row.kind,
                credits=row.credits + (kind.credits if kind else 0),
                calls=row.calls + (kind.calls if kind else 0),
            )
        return CreditBurn(
            month=month,
            starts_at=starts_at,
            ends_at=ends_at,
            total_credits=sum(row.credits for row in rows),
            total_calls=sum(row.calls for row in rows),
            by_sport=sorted(by_sport.values(), key=lambda s: (-s.credits, s.sport_key)),
            by_kind=sorted(by_kind.values(), key=lambda k: (-k.credits, k.kind.value)),
        )
