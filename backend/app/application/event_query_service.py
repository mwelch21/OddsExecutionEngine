import logging
from datetime import UTC, datetime
from time import perf_counter

from backend.app.application.ports import EventReadUnitOfWorkFactory, SportCatalog
from backend.app.domain.models import (
    EventFilter,
    EventPage,
    LineBoard,
    LineBoardMarket,
    MarketQuotes,
)
from backend.app.engines.recommendation_engine import RecommendationEngine


class EventQueryService:
    """Read stored events: the browse list, and one event's line board.

    Pure read path: no unit-of-work events are staged and nothing is published.
    `now` is taken once per request so the count and the page agree on which
    events have already started.
    """

    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        unit_of_work_factory: EventReadUnitOfWorkFactory,
        recommendation_engine: RecommendationEngine,
        sport_catalog: SportCatalog,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._recommendation_engine = recommendation_engine
        self._sport_catalog = sport_catalog

    def list_events(
        self,
        event_filter: EventFilter,
        page: int = 1,
        page_size: int = 25,
        sport_keys: list[str] | None = None,
    ) -> EventPage:
        """`sport_keys` narrows to events in any of those catalog sports (#132).

        A key maps to its stored (sport, league) through the catalog, the same
        pairing Auto-Refresh uses. A key outside the catalog matches no event,
        as an unknown league does. None or empty: no sport-key filter.
        """
        started_at = perf_counter()
        now = datetime.now(UTC)
        if sport_keys:
            event_filter = event_filter.model_copy(
                update={"sport_leagues": self._sport_leagues_for(sport_keys)}
            )

        try:
            with self._unit_of_work_factory() as uow:
                total_events = uow.count_events(event_filter, now)
                offset = (page - 1) * page_size
                # A page past the end is empty rather than an error: the set moves
                # under the reader as events start.
                events = (
                    uow.list_events(event_filter, now, limit=page_size, offset=offset)
                    if offset < total_events
                    else []
                )
        except Exception:
            self._logger.exception(
                "events.list.failed",
                extra={
                    "path": "/api/v1/events",
                    "league": event_filter.league,
                    "sport": event_filter.sport,
                    "sport_keys": sport_keys,
                    "page": page,
                    "page_size": page_size,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise

        self._logger.info(
            "events.list.completed",
            extra={
                "path": "/api/v1/events",
                "league": event_filter.league,
                "sport": event_filter.sport,
                "sport_keys": sport_keys,
                "status": event_filter.status.value,
                "page": page,
                "page_size": page_size,
                "total_events": total_events,
                "returned_count": len(events),
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return EventPage(
            events=events,
            page=page,
            page_size=page_size,
            total_events=total_events,
        )

    def _sport_leagues_for(self, sport_keys: list[str]) -> tuple[tuple[str, str | None], ...]:
        wanted = set(sport_keys)
        return tuple(
            sorted(
                {
                    (entry.sport, entry.league)
                    for entry in self._sport_catalog.list_supported_sports()
                    if entry.key in wanted
                },
                key=lambda pair: (pair[0], pair[1] or ""),
            )
        )

    def get_line_board(self, event_id: str) -> LineBoard | None:
        """One event's markets, each ranked best-first. None when no such event.

        Unpaged by design: a single event's board is bounded and renders as one
        screen, so paging it would only make a client reassemble it.
        """
        started_at = perf_counter()

        try:
            with self._unit_of_work_factory() as uow:
                event = uow.get_event(event_id)
                markets = uow.list_market_quotes(event_id) if event is not None else []
        except Exception:
            self._logger.exception(
                "events.line_board.failed",
                extra={
                    "path": "/api/v1/events/{event_id}/quotes",
                    "event_id": event_id,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            raise

        if event is None:
            self._logger.info(
                "events.line_board.not_found",
                extra={"event_id": event_id},
            )
            return None

        ranked_markets = [self._to_board_market(market) for market in markets]
        self._logger.info(
            "events.line_board.completed",
            extra={
                "path": "/api/v1/events/{event_id}/quotes",
                "event_id": event_id,
                "market_count": len(ranked_markets),
                "quote_count": sum(len(m.quotes) for m in ranked_markets),
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return LineBoard(event=event, markets=ranked_markets)

    def _to_board_market(self, market: MarketQuotes) -> LineBoardMarket:
        """Rank one market's books with the engine rule, not a second sort.

        Two books at an identical price are separated only by the engine's
        tie-break. Ranking here rather than in the client is what keeps the book
        the board calls best and the book a watch would fire on the same book.
        """
        return LineBoardMarket.from_ranked(
            market, self._recommendation_engine.rank_quotes(market.quotes)
        )
