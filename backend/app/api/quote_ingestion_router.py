from fastapi import APIRouter

from backend.app.api.quote_ingestion_schemas import (
    QuoteRefreshRequest,
    QuoteRefreshResponse,
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

    return router
