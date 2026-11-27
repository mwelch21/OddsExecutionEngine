from fastapi import APIRouter, HTTPException, Query

from backend.app.api.event_schemas import EventListResponse, LineBoardResponse
from backend.app.application.event_query_service import EventQueryService
from backend.app.domain.models import EventFilter, EventListStatus

LEAGUE_QUERY = Query(default=None, description="Exact league code, e.g. NFL.")
SPORT_QUERY = Query(default=None, description="Exact sport key, e.g. americanfootball.")
SPORT_KEY_QUERY = Query(
    default=None,
    description=(
        "Catalog sport key from GET /api/v1/sports, e.g. basketball_nba. Repeat for "
        "several; an event in any of them matches. A key outside the catalog matches "
        "nothing. Combines with sport and league."
    ),
)
STATUS_QUERY = Query(
    default=None,
    description=(
        "upcoming, live, or all (upcoming plus live; the default). "
        "Ended events are never listed."
    ),
)
INCLUDE_STARTED_QUERY = Query(
    default=None,
    deprecated=True,
    description="Deprecated: use status. true reads as status=all, false as status=upcoming.",
)
PAGE_QUERY = Query(default=1, ge=1)
PAGE_SIZE_QUERY = Query(default=25, ge=1, le=100)


def create_event_router(service: EventQueryService) -> APIRouter:
    router = APIRouter(tags=["events"])

    @router.get("/events", response_model=EventListResponse)
    def list_events(
        league: str | None = LEAGUE_QUERY,
        sport: str | None = SPORT_QUERY,
        sport_key: list[str] | None = SPORT_KEY_QUERY,
        status: EventListStatus | None = STATUS_QUERY,
        include_started: bool | None = INCLUDE_STARTED_QUERY,
        page: int = PAGE_QUERY,
        page_size: int = PAGE_SIZE_QUERY,
    ) -> EventListResponse:
        return EventListResponse.from_domain(
            service.list_events(
                EventFilter(
                    league=league,
                    sport=sport,
                    status=EventListStatus.resolve(status, include_started),
                ),
                page=page,
                page_size=page_size,
                sport_keys=sport_key,
            )
        )

    @router.get("/events/{event_id}/quotes", response_model=LineBoardResponse)
    def get_line_board(event_id: str) -> LineBoardResponse:
        board = service.get_line_board(event_id)
        if board is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return LineBoardResponse.from_domain(board)

    return router

