from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from backend.app.application.recommendation_service import RecommendationService
from backend.app.domain.models import ExecutionRecommendation, MarketType, OrderIntent, Quote

router = APIRouter(tags=["execution"])


class RecommendationRequest(BaseModel):
    event_id: str = Field(min_length=1)
    market_type: MarketType
    selection: str = Field(min_length=1)
    line: float | None = None
    target_price: int

    @model_validator(mode="after")
    def validate_market_fields(self) -> "RecommendationRequest":
        if self.market_type is MarketType.MONEYLINE and self.line is not None:
            raise ValueError("line must be omitted for moneyline requests")

        if self.market_type in {MarketType.SPREAD, MarketType.TOTAL} and self.line is None:
            raise ValueError("line is required for spread and total requests")

        if self.market_type is MarketType.TOTAL and self.selection not in {"over", "under"}:
            raise ValueError("selection must be 'over' or 'under' for total requests")

        return self


class QuoteResponse(BaseModel):
    sportsbook: str
    selection: str
    price: int
    line: float | None

    @classmethod
    def from_domain(cls, quote: Quote) -> "QuoteResponse":
        return cls(
            sportsbook=quote.sportsbook,
            selection=quote.selection,
            price=quote.price,
            line=quote.line,
        )


class IntentSummaryResponse(BaseModel):
    event_id: str
    market_type: MarketType
    selection: str
    line: float | None
    target_price: int

    @classmethod
    def from_domain(cls, intent: OrderIntent) -> "IntentSummaryResponse":
        return cls(
            event_id=intent.event_id,
            market_type=intent.market_type,
            selection=intent.selection,
            line=intent.line,
            target_price=intent.target_price,
        )


class RecommendationResponse(BaseModel):
    request: IntentSummaryResponse
    fillable: bool
    best_quote: QuoteResponse | None
    ranked_quotes: list[QuoteResponse]
    nearest_miss: QuoteResponse | None
    matched_quote_count: int

    @classmethod
    def from_domain(cls, recommendation: ExecutionRecommendation) -> "RecommendationResponse":
        return cls(
            request=IntentSummaryResponse.from_domain(recommendation.intent),
            fillable=recommendation.fillable,
            best_quote=(
                QuoteResponse.from_domain(recommendation.best_quote)
                if recommendation.best_quote is not None
                else None
            ),
            ranked_quotes=[
                QuoteResponse.from_domain(quote) for quote in recommendation.ranked_quotes
            ],
            nearest_miss=(
                QuoteResponse.from_domain(recommendation.nearest_miss)
                if recommendation.nearest_miss is not None
                else None
            ),
            matched_quote_count=recommendation.matched_quote_count,
        )


def create_recommendation_router(service: RecommendationService) -> APIRouter:
    recommendation_router = APIRouter()

    @recommendation_router.post(
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

    recommendation_router.include_router(router)
    return recommendation_router
