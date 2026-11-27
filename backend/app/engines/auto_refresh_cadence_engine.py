from collections.abc import Collection, Iterable, Mapping
from datetime import UTC, datetime, timedelta


class AutoRefreshCadenceEngine:
    """Which watched sports are due a refresh: the derived cooldown of ADR-016.

    A sport is due when it has never been pulled sport-wide, or when its last
    sport-wide pull is at least one interval old. There is no stored due time,
    so a manual pull pushes the next automatic one back by itself.

    Two intervals, both set by the operator (#128). A candidate sport in
    `live_sports` runs on the live interval; every other one on the upcoming
    interval. Nothing here changes either interval.
    """

    def interval_minutes_for(
        self,
        sport: str,
        live_sports: Collection[str],
        interval_minutes: int,
        live_interval_minutes: int,
    ) -> int:
        return live_interval_minutes if sport in live_sports else interval_minutes

    def due_sports(
        self,
        candidate_sports: Iterable[str],
        live_sports: Collection[str],
        last_refreshed_at: Mapping[str, datetime],
        interval_minutes: int,
        live_interval_minutes: int,
        now: datetime,
    ) -> list[str]:
        now_aware = _aware(now)
        due = []
        for sport in sorted(set(candidate_sports)):
            interval = timedelta(
                minutes=self.interval_minutes_for(
                    sport, live_sports, interval_minutes, live_interval_minutes
                )
            )
            last = last_refreshed_at.get(sport)
            if last is None or _aware(last) + interval <= now_aware:
                due.append(sport)
        return due


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
