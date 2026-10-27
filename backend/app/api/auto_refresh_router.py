from fastapi import APIRouter

from backend.app.api.auto_refresh_schemas import (
    AutoRefreshResponse,
    AutoRefreshSettingsRequest,
)
from backend.app.application.auto_refresh_service import AutoRefreshService


def create_auto_refresh_router(service: AutoRefreshService) -> APIRouter:
    router = APIRouter(tags=["auto-refresh"])

    @router.get("/auto-refresh", response_model=AutoRefreshResponse)
    def get_auto_refresh() -> AutoRefreshResponse:
        return AutoRefreshResponse.from_domain(service.get_status())

    # Only changes settings. Turning the switch on never refreshes from here: the
    # worker's next poll does, so the API itself still never pulls on its own.
    @router.put("/auto-refresh", response_model=AutoRefreshResponse)
    def put_auto_refresh(request: AutoRefreshSettingsRequest) -> AutoRefreshResponse:
        return AutoRefreshResponse.from_domain(service.update_settings(request.to_domain()))

    return router
