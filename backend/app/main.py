from fastapi import FastAPI

from backend.app.api.recommendation_router import create_recommendation_router
from backend.app.application.recommendation_service import RecommendationService
from backend.app.config import Settings, get_settings
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.recommendation_uow import (
    SqlAlchemyRecommendationUnitOfWork,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    session_factory = DatabaseSessionFactory(app_settings.database_url)
    app = FastAPI(title=app_settings.app_name)
    app.state.session_factory = session_factory
    recommendation_service = RecommendationService(
        unit_of_work_factory=lambda: SqlAlchemyRecommendationUnitOfWork(session_factory),
        quote_matching_engine=QuoteMatchingEngine(),
        recommendation_engine=RecommendationEngine(PriceComparisonService()),
    )

    @app.get("/health", tags=["system"])
    def healthcheck() -> dict[str, str]:
        return {
            "status": "ok",
            "environment": app_settings.app_env,
        }

    app.include_router(create_recommendation_router(recommendation_service))

    return app


app = create_app()
