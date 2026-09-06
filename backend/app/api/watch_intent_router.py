from fastapi import APIRouter, HTTPException, Query, status

from backend.app.api.watch_intent_schemas import (
    WatchIntentCreateRequest,
    WatchIntentListResponse,
    WatchIntentResponse,
)
from backend.app.application.watch_intent_service import WatchIntentService
from backend.app.domain.models import WatchStatus

EVENT_ID_QUERY = Query(default=None)
STATUS_QUERY = Query(default=None, alias="status")


def create_watch_intent_router(service: WatchIntentService) -> APIRouter:
    router = APIRouter(tags=["monitoring"])

    @router.post(
        "/watch-intents",
        response_model=WatchIntentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_watch_intent(request: WatchIntentCreateRequest) -> WatchIntentResponse:
        watch_intent = service.create_watch(request.to_domain())
        return WatchIntentResponse.from_domain(watch_intent)

    @router.get("/watch-intents", response_model=WatchIntentListResponse)
    def list_watch_intents(
        event_id: str | None = EVENT_ID_QUERY,
        watch_status: WatchStatus | None = STATUS_QUERY,
    ) -> WatchIntentListResponse:
        watch_intents = service.list_watches(event_id=event_id, status=watch_status)
        return WatchIntentListResponse.from_domain(watch_intents)

    @router.get("/watch-intents/{watch_intent_id}", response_model=WatchIntentResponse)
    def get_watch_intent(watch_intent_id: str) -> WatchIntentResponse:
        watch_intent = service.get_watch(watch_intent_id)
        if watch_intent is None:
            raise HTTPException(status_code=404, detail="Watch intent not found")
        return WatchIntentResponse.from_domain(watch_intent)

    @router.delete("/watch-intents/{watch_intent_id}", response_model=WatchIntentResponse)
    def cancel_watch_intent(watch_intent_id: str) -> WatchIntentResponse:
        watch_intent = service.cancel_watch(watch_intent_id)
        if watch_intent is None:
            raise HTTPException(status_code=404, detail="Watch intent not found")
        return WatchIntentResponse.from_domain(watch_intent)

    return router
