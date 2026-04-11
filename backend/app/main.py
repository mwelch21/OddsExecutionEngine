from fastapi import FastAPI

from backend.app.api.recommendation import create_recommendation_router
from backend.app.application.recommendation_service import RecommendationService
from backend.app.config import Settings, get_settings
from backend.app.infrastructure.quote_provider import InMemoryQuoteProvider


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    app = FastAPI(title=app_settings.app_name)
    recommendation_service = RecommendationService(InMemoryQuoteProvider())

    @app.get("/health", tags=["system"])
    def healthcheck() -> dict[str, str]:
        return {
            "status": "ok",
            "environment": app_settings.app_env,
        }

    app.include_router(create_recommendation_router(recommendation_service))

    return app


app = create_app()
