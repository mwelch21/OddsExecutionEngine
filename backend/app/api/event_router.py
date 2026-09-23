from fastapi import APIRouter, HTTPException, Query

from backend.app.api.event_schemas import EventListResponse, LineBoardResponse
from backend.app.application.event_query_service import EventQueryService
from backend.app.domain.models import EventFilter

LEAGUE_QUERY = Query(default=None, description="Exact league code, e.g. NFL.")
SPORT_QUERY = Query(default=None, description="Exact sport key, e.g. americanfootball.")
INCLUDE_STARTED_QUERY = Query(
    default=False,
    description="Include events already under way. They can no longer be filled.",
)
PAGE_QUERY = Query(default=1, ge=1)
PAGE_SIZE_QUERY = Query(default=25, ge=1, le=100)


def create_event_router(service: EventQueryService) -> APIRouter:
    router = APIRouter(tags=["events"])

    @router.get("/events", response_model=EventListResponse)
    def list_events(
        league: str | None = LEAGUE_QUERY,
        sport: str | None = SPORT_QUERY,
        include_started: bool = INCLUDE_STARTED_QUERY,
        page: int = PAGE_QUERY,
        page_size: int = PAGE_SIZE_QUERY,
    ) -> EventListResponse:
        return EventListResponse.from_domain(
            service.list_events(
                EventFilter(
                    league=league,
                    sport=sport,
                    include_started=include_started,
                ),
                page=page,
                page_size=page_size,
            )
        )

    @router.get("/events/{event_id}/quotes", response_model=LineBoardResponse)
    def get_line_board(event_id: str) -> LineBoardResponse:
        board = service.get_line_board(event_id)
        if board is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return LineBoardResponse.from_domain(board)

    return router
