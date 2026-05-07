from fastapi import APIRouter

from backend.app.api.quote_ingestion_schemas import (
    QuoteRefreshRequest,
    QuoteRefreshResponse,
    SportRefreshRequest,
    SportRefreshResponse,
)
from backend.app.application.quote_ingestion_service import QuoteIngestionService


def create_quote_ingestion_router(service: QuoteIngestionService) -> APIRouter:
    router = APIRouter(tags=["ingestion"])

    @router.post(
        "/ingestion/quotes/refresh",
        response_model=QuoteRefreshResponse,
    )
    def refresh_quotes(request: QuoteRefreshRequest) -> QuoteRefreshResponse:
        summary = service.refresh_quotes(request.event_id)
        return QuoteRefreshResponse.from_domain(summary)

    @router.post(
        "/ingestion/quotes/refresh-sport",
        response_model=SportRefreshResponse,
    )
    def refresh_sport(request: SportRefreshRequest) -> SportRefreshResponse:
        summaries = service.refresh_sport(request.sport)
        return SportRefreshResponse(
            sport=request.sport,
            events_refreshed=len(summaries),
            results=[QuoteRefreshResponse.from_domain(s) for s in summaries],
        )

    return router
