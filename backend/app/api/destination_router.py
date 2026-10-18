from fastapi import APIRouter, HTTPException, Response

from backend.app.api.destination_schemas import (
    DestinationListResponse,
    DestinationResponse,
    RegisterWebPushRequest,
    SendTestResponse,
    VapidPublicKeyResponse,
)
from backend.app.application.destination_service import (
    DestinationInactiveError,
    DestinationNotFoundError,
    DestinationService,
    SendTestRateLimitedError,
)
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

    @router.post(
        "/destinations/{destination_id}/test",
        response_model=SendTestResponse,
        status_code=202,
    )
    def send_test(destination_id: str) -> SendTestResponse:
        try:
            event = service.send_test(destination_id)
        except DestinationNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except DestinationInactiveError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except SendTestRateLimitedError as error:
            raise HTTPException(
                status_code=429,
                detail=str(error),
                headers={"Retry-After": str(error.retry_after_seconds)},
            ) from error
        return SendTestResponse(
            public_event_id=event.id, destination_id=destination_id
        )

    return router
