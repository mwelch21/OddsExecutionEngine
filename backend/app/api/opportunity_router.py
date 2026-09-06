from fastapi import APIRouter, HTTPException, Query

from backend.app.api.opportunity_schemas import OpportunityListResponse, OpportunityResponse
from backend.app.application.watch_evaluation_service import WatchEvaluationService

EVENT_ID_QUERY = Query(default=None)


def create_opportunity_router(service: WatchEvaluationService) -> APIRouter:
    router = APIRouter(tags=["monitoring"])

    @router.get("/opportunities", response_model=OpportunityListResponse)
    def list_opportunities(event_id: str | None = EVENT_ID_QUERY) -> OpportunityListResponse:
        return OpportunityListResponse.from_domain(service.list_opportunities(event_id=event_id))

    @router.get("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
    def get_opportunity(opportunity_id: str) -> OpportunityResponse:
        opportunity_signal = service.get_opportunity(opportunity_id)
        if opportunity_signal is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return OpportunityResponse.from_domain(opportunity_signal)

    return router
