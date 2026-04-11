from fastapi import APIRouter

from backend.app.api.recommendation_schemas import RecommendationRequest, RecommendationResponse
from backend.app.application.recommendation_service import RecommendationService
from backend.app.domain.models import OrderIntent


def create_recommendation_router(service: RecommendationService) -> APIRouter:
    router = APIRouter(tags=["execution"])

    @router.post(
        "/execution/recommendation",
        response_model=RecommendationResponse,
    )
    def get_recommendation(request: RecommendationRequest) -> RecommendationResponse:
        intent = OrderIntent(
            event_id=request.event_id,
            market_type=request.market_type,
            selection=request.selection,
            line=request.line,
            target_price=request.target_price,
        )
        recommendation = service.recommend(intent)
        return RecommendationResponse.from_domain(recommendation)

    return router
