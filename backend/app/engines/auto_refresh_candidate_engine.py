from collections.abc import Iterable
from datetime import UTC, datetime

from backend.app.domain.auto_refresh import CandidateSport, WatchedEvent
from backend.app.domain.models import EventStatus, WatchWindow


class AutoRefreshCandidateEngine:
    """Which sports a refresh can serve now, seen from the evaluator (#128, ADR-016).

    A watch makes its sport a candidate when evaluation would act on it after a
    pull:

    - a `pre_game` or `full_game` watch on an `upcoming` event, or
    - a `live` or `full_game` watch on a `live` event.

    An `ended` event never counts. The rule reads the stored event status and the
    watch window. It reads the start time in one case only, the same one the
    evaluator does: a `pre_game` window closes once the stored start has passed,
    even on an event still stored `upcoming` (ADR-017). A `full_game` watch on
    such an event stays a candidate, because the pull is what observes kickoff.

    Callers pass only active watches whose TTL has not passed.
    """

    def acts_on(self, watched: WatchedEvent, now: datetime) -> bool:
        if watched.status is EventStatus.ENDED:
            return False
        if watched.status is EventStatus.LIVE:
            return watched.window is not WatchWindow.PRE_GAME
        if watched.window is WatchWindow.LIVE:
            return False
        if watched.window is WatchWindow.PRE_GAME:
            return not _has_started(watched.starts_at, now)
        return True

    def candidates(self, watched: Iterable[WatchedEvent], now: datetime) -> list[CandidateSport]:
        """Each stored (sport, league) with a watch evaluation acts on, once.

        A sport is `live` when any of its candidate watches is on a live event.
        Sorted, so the result does not depend on storage order.
        """
        live_by_sport: dict[tuple[str, str | None], bool] = {}
        for item in watched:
            if not self.acts_on(item, now):
                continue
            key = (item.sport, item.league)
            live_by_sport[key] = live_by_sport.get(key, False) or (item.status is EventStatus.LIVE)
        return [
            CandidateSport(sport=sport, league=league, live=live)
            for (sport, league), live in sorted(
                live_by_sport.items(), key=lambda entry: (entry[0][0], entry[0][1] or "")
            )
        ]


def _has_started(starts_at: datetime | None, now: datetime) -> bool:
    if starts_at is None:
        return False
    aware = starts_at if starts_at.tzinfo is not None else starts_at.replace(tzinfo=UTC)
    return aware <= now
