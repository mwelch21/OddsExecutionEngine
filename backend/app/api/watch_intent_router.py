from fastapi import APIRouter, HTTPException

from backend.app.api.watch_intent_schemas import (
    CreateWatchIntentRequest,
    WatchIntentListResponse,
    WatchIntentResponse,
)
from backend.app.application.watch_intent_service import WatchIntentService


def create_watch_intent_router(service: WatchIntentService) -> APIRouter:
    router = APIRouter(tags=["watch"])

    @router.post(
        "/watch-intents",
        response_model=WatchIntentResponse,
        status_code=201,
    )
    def create_watch_intent(request: CreateWatchIntentRequest) -> WatchIntentResponse:
        intent = service.create_watch_intent(
            event_id=request.event_id,
            market_type=request.market_type,
            selection=request.selection,
            target_price=request.target_price,
            line=request.line,
        )
        return WatchIntentResponse.from_domain(intent)

    @router.get(
        "/watch-intents",
        response_model=WatchIntentListResponse,
    )
    def list_watch_intents(event_id: str | None = None) -> WatchIntentListResponse:
        intents = service.list_watch_intents(event_id)
        return WatchIntentListResponse.from_domain(intents)

    @router.delete(
        "/watch-intents/{watch_intent_id}",
        response_model=WatchIntentResponse,
    )
    def cancel_watch_intent(watch_intent_id: str) -> WatchIntentResponse:
        try:
            intent = service.cancel_watch_intent(watch_intent_id)
        except ValueError as err:
            raise HTTPException(status_code=404, detail="Watch intent not found") from err
        return WatchIntentResponse.from_domain(intent)

    return router
