from fastapi import APIRouter, HTTPException, Query

from backend.app.api.watch_intent_schemas import (
    CreateWatchIntentRequest,
    CreateWatchIntentResponse,
    WatchIntentListResponse,
    WatchIntentResponse,
)
from backend.app.application.watch_intent_service import (
    WatchIntentAlreadyTriggeredError,
    WatchIntentService,
)
from backend.app.domain.models import WatchStatus

EVENT_ID_QUERY = Query(default=None)
STATUS_QUERY = Query(default=None, alias="status")


def create_watch_intent_router(service: WatchIntentService) -> APIRouter:
    router = APIRouter(tags=["watch"])

    @router.post(
        "/watch-intents",
        response_model=CreateWatchIntentResponse,
        status_code=201,
    )
    def create_watch_intent(
        request: CreateWatchIntentRequest,
    ) -> CreateWatchIntentResponse:
        result = service.create_watch_intent(
            event_id=request.event_id,
            market_type=request.market_type,
            selection=request.selection,
            target_price=request.target_price,
            line=request.line,
            expires_at=request.expires_at,
        )
        return CreateWatchIntentResponse.from_creation(result)

    @router.get(
        "/watch-intents",
        response_model=WatchIntentListResponse,
    )
    def list_watch_intents(
        event_id: str | None = EVENT_ID_QUERY,
        watch_status: WatchStatus | None = STATUS_QUERY,
    ) -> WatchIntentListResponse:
        intents = service.list_watch_intents(event_id, watch_status)
        return WatchIntentListResponse.from_domain(intents)

    @router.get(
        "/watch-intents/{watch_intent_id}",
        response_model=WatchIntentResponse,
    )
    def get_watch_intent(watch_intent_id: str) -> WatchIntentResponse:
        intent = service.get_watch_intent(watch_intent_id)
        if intent is None:
            raise HTTPException(status_code=404, detail="Watch intent not found")
        return WatchIntentResponse.from_domain(intent)

    @router.delete(
        "/watch-intents/{watch_intent_id}",
        response_model=WatchIntentResponse,
    )
    def cancel_watch_intent(watch_intent_id: str) -> WatchIntentResponse:
        try:
            intent = service.cancel_watch_intent(watch_intent_id)
        except WatchIntentAlreadyTriggeredError as err:
            raise HTTPException(
                status_code=409,
                detail="Watch intent has already been triggered",
            ) from err
        except ValueError as err:
            raise HTTPException(status_code=404, detail="Watch intent not found") from err
        return WatchIntentResponse.from_domain(intent)

    return router
