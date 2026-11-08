from fastapi import APIRouter, Query

from backend.app.api.admin.refreshes_schemas import RefreshListResponse
from backend.app.application.admin_query_service import AdminQueryService
from backend.app.domain.refresh_records import (
    RefreshOutcomeStatus,
    RefreshRecordFilter,
    RefreshTrigger,
)

SPORT_QUERY = Query(default=None, description="Exact provider sport key, e.g. basketball_nba.")
TRIGGER_QUERY = Query(default=None)
OUTCOME_QUERY = Query(default=None)
PAGE_QUERY = Query(default=1, ge=1)
PAGE_SIZE_QUERY = Query(default=50, ge=1, le=200)


def create_refreshes_router(service: AdminQueryService) -> APIRouter:
    router = APIRouter(tags=["admin"])

    @router.get("/refreshes", response_model=RefreshListResponse)
    def list_refreshes(
        sport: str | None = SPORT_QUERY,
        trigger: RefreshTrigger | None = TRIGGER_QUERY,
        outcome: RefreshOutcomeStatus | None = OUTCOME_QUERY,
        page: int = PAGE_QUERY,
        page_size: int = PAGE_SIZE_QUERY,
    ) -> RefreshListResponse:
        return RefreshListResponse.from_domain(
            service.list_refreshes(
                RefreshRecordFilter(sport_key=sport, trigger=trigger, outcome=outcome),
                page=page,
                page_size=page_size,
            )
        )

    return router
