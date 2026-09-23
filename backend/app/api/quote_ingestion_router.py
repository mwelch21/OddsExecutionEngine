from fastapi import APIRouter, HTTPException

from backend.app.api.quote_ingestion_schemas import (
    QuoteRefreshRequest,
    QuoteRefreshResponse,
    SportRefreshRequest,
    SportRefreshResponse,
    SupportedSportResponse,
    SupportedSportsResponse,
)
from backend.app.application.quote_ingestion_service import (
    QuoteIngestionService,
    UnsupportedSportError,
)


def create_quote_ingestion_router(service: QuoteIngestionService) -> APIRouter:
    router = APIRouter(tags=["ingestion"])

    @router.post(
        "/ingestion/quotes/refresh",
        response_model=QuoteRefreshResponse,
    )
    def refresh_quotes(request: QuoteRefreshRequest) -> QuoteRefreshResponse:
        summary = service.refresh_quotes(request.event_id)
        return QuoteRefreshResponse.from_domain(summary)

    @router.get(
        "/sports",
        response_model=SupportedSportsResponse,
    )
    def list_supported_sports() -> SupportedSportsResponse:
        return SupportedSportsResponse(
            sports=[
                SupportedSportResponse.from_domain(sport)
                for sport in service.list_supported_sports()
            ]
        )

    @router.post(
        "/ingestion/quotes/refresh-sport",
        response_model=SportRefreshResponse,
    )
    def refresh_sport(request: SportRefreshRequest) -> SportRefreshResponse:
        try:
            result = service.refresh_sport(request.sport)
        except UnsupportedSportError as err:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unsupported sport '{err.sport}'. "
                    f"Supported: {', '.join(err.supported)}"
                ),
            ) from err
        return SportRefreshResponse.from_domain(result)

    return router
