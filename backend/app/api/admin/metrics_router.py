from fastapi import APIRouter

from backend.app.api.admin.metrics_schemas import MetricsResponse
from backend.app.application.system_status_query_service import SystemStatusQueryService


def create_metrics_router(service: SystemStatusQueryService) -> APIRouter:
    router = APIRouter(tags=["admin"])

    @router.get("/metrics", response_model=MetricsResponse)
    def get_metrics() -> MetricsResponse:
        return MetricsResponse.from_domain(service.metrics())

    return router
