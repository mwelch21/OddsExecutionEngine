from fastapi import APIRouter

from backend.app.api.opportunity_schemas import OpportunityListResponse
from backend.app.application.watch_intent_service import WatchIntentService


def create_opportunity_router(service: WatchIntentService) -> APIRouter:
    router = APIRouter(tags=["watch"])

    @router.get(
        "/opportunities",
        response_model=OpportunityListResponse,
    )
    def list_opportunities(event_id: str | None = None) -> OpportunityListResponse:
        items = service.list_opportunities(event_id)
        return OpportunityListResponse.from_domain(items)

    return router
