from fastapi import APIRouter, HTTPException, Response

from backend.app.api.destination_schemas import (
    DestinationListResponse,
    DestinationResponse,
    RegisterWebPushRequest,
    VapidPublicKeyResponse,
)
from backend.app.application.destination_service import DestinationService
from backend.app.domain.destinations import WebPushKeys


def create_destination_router(
    service: DestinationService, vapid_public_key: str
) -> APIRouter:
    router = APIRouter(tags=["notifications"])

    @router.get("/push/vapid-public-key", response_model=VapidPublicKeyResponse)
    def get_vapid_public_key() -> VapidPublicKeyResponse:
        if not vapid_public_key:
            raise HTTPException(
                status_code=503,
                detail="Web Push is not configured: set VAPID_PUBLIC_KEY.",
            )
        return VapidPublicKeyResponse(public_key=vapid_public_key)

    @router.post("/destinations/web-push", response_model=DestinationResponse)
    def register_web_push(
        request: RegisterWebPushRequest, response: Response
    ) -> DestinationResponse:
        destination, created = service.register_web_push(
            address=request.endpoint,
            keys=WebPushKeys(p256dh=request.keys.p256dh, auth=request.keys.auth),
            label=request.label,
        )
        response.status_code = 201 if created else 200
        return DestinationResponse.from_domain(destination)

    @router.get("/destinations", response_model=DestinationListResponse)
    def list_destinations() -> DestinationListResponse:
        return DestinationListResponse(
            destinations=[
                DestinationResponse.from_domain(d) for d in service.list_destinations()
            ]
        )

    return router
