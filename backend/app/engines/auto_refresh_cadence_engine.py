from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta


class AutoRefreshCadenceEngine:
    """Which watched sports are due a refresh: the derived cooldown of ADR-016.

    A sport is due when it has never been pulled sport-wide, or when its last
    sport-wide pull is at least one interval old. There is no stored due time,
    so a manual pull pushes the next automatic one back by itself.
    """

    def due_sports(
        self,
        candidate_sports: Iterable[str],
        last_refreshed_at: Mapping[str, datetime],
        interval_minutes: int,
        now: datetime,
    ) -> list[str]:
        interval = timedelta(minutes=interval_minutes)
        now_aware = _aware(now)
        due = []
        for sport in sorted(set(candidate_sports)):
            last = last_refreshed_at.get(sport)
            if last is None or _aware(last) + interval <= now_aware:
                due.append(sport)
        return due


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
