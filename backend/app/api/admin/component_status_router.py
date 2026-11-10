from fastapi import APIRouter

from backend.app.api.admin.component_status_schemas import ComponentStatusListResponse
from backend.app.application.system_status_query_service import SystemStatusQueryService


def create_component_status_router(service: SystemStatusQueryService) -> APIRouter:
    router = APIRouter(tags=["admin"])

    @router.get("/component-status", response_model=ComponentStatusListResponse)
    def get_component_status() -> ComponentStatusListResponse:
        return ComponentStatusListResponse.from_domain(service.component_statuses())

    return router
