from fastapi import APIRouter, HTTPException, Query

from backend.app.api.opportunity_schemas import (
    OpportunityListResponse,
    OpportunityResponse,
)
from backend.app.application.watch_intent_service import WatchIntentService

EVENT_ID_QUERY = Query(default=None)


def create_opportunity_router(service: WatchIntentService) -> APIRouter:
    router = APIRouter(tags=["watch"])

    @router.get(
        "/opportunities",
        response_model=OpportunityListResponse,
    )
    def list_opportunities(
        event_id: str | None = EVENT_ID_QUERY,
    ) -> OpportunityListResponse:
        items = service.list_opportunities(event_id)
        return OpportunityListResponse.from_domain(items)

    @router.get(
        "/opportunities/{opportunity_id}",
        response_model=OpportunityResponse,
    )
    def get_opportunity(opportunity_id: str) -> OpportunityResponse:
        item = service.get_opportunity(opportunity_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return OpportunityResponse.from_domain(item)

    return router
