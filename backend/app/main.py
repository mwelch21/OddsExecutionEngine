import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from backend.app.api.opportunity_router import create_opportunity_router
from backend.app.api.quote_ingestion_router import create_quote_ingestion_router
from backend.app.api.recommendation_router import create_recommendation_router
from backend.app.api.watch_intent_router import create_watch_intent_router
from backend.app.application.ports import QuoteIngestionProvider
from backend.app.application.quote_ingestion_service import QuoteIngestionService
from backend.app.application.recommendation_service import RecommendationService
from backend.app.application.watch_intent_service import WatchIntentService
from backend.app.config import Settings, get_settings
from backend.app.engines.normalization_engine import NormalizationEngine
from backend.app.engines.opportunity_validity_engine import OpportunityValidityEngine
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine
from backend.app.infrastructure.observability.logging import configure_logging
from backend.app.infrastructure.observability.request_context import (
    reset_request_id,
    set_request_id,
)
from backend.app.infrastructure.odds_api_provider import TheOddsApiProvider
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.quote_ingestion_uow import (
    SqlAlchemyQuoteIngestionUnitOfWork,
)
from backend.app.infrastructure.persistence.recommendation_uow import (
    SqlAlchemyRecommendationUnitOfWork,
)
from backend.app.infrastructure.persistence.watch_intent_uow import (
    SqlAlchemyWatchIntentUnitOfWork,
)
from backend.app.infrastructure.publishers.logging_publisher import (
    LoggingWorkflowEventPublisher,
)
from backend.app.infrastructure.quote_provider import InMemoryQuoteProvider


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings)
    session_factory = DatabaseSessionFactory(app_settings.database_url)
    app = FastAPI(title=app_settings.app_name)
    app.state.session_factory = session_factory
    app_logger = logging.getLogger(__name__)
    workflow_event_publisher = LoggingWorkflowEventPublisher()
    price_comparison_service = PriceComparisonService()
    recommendation_engine = RecommendationEngine(price_comparison_service)
    recommendation_service = RecommendationService(
        unit_of_work_factory=lambda: SqlAlchemyRecommendationUnitOfWork(session_factory),
        workflow_event_publisher=workflow_event_publisher,
        quote_matching_engine=QuoteMatchingEngine(),
        recommendation_engine=recommendation_engine,
    )
    watch_intent_service = WatchIntentService(
        unit_of_work_factory=lambda: SqlAlchemyWatchIntentUnitOfWork(session_factory),
        workflow_event_publisher=workflow_event_publisher,
        watch_evaluation_engine=WatchEvaluationEngine(
            price_comparison_service,
            recommendation_engine,
        ),
        opportunity_validity_engine=OpportunityValidityEngine(),
        opportunity_ttl_minutes=app_settings.opportunity_ttl_minutes,
    )
    quote_provider: QuoteIngestionProvider
    if app_settings.quote_provider == "odds_api":
        quote_provider = TheOddsApiProvider(
            api_key=app_settings.odds_api_key,
            sports=[s.strip() for s in app_settings.odds_api_sports.split(",")],
            regions=[r.strip() for r in app_settings.odds_api_regions.split(",")],
            markets=[m.strip() for m in app_settings.odds_api_markets.split(",")],
        )
    else:
        quote_provider = InMemoryQuoteProvider()

    quote_ingestion_service = QuoteIngestionService(
        unit_of_work_factory=lambda: SqlAlchemyQuoteIngestionUnitOfWork(session_factory),
        quote_provider=quote_provider,
        normalization_engine=NormalizationEngine(),
        workflow_event_publisher=workflow_event_publisher,
        watch_intent_service=watch_intent_service,
    )

    @app.middleware("http")
    async def add_request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        context_token = set_request_id(request_id)
        started_at = perf_counter()
        app_logger.info(
            "http.request.started",
            extra={
                "method": request.method,
                "path": request.url.path,
            },
        )
        try:
            response = await call_next(request)
        except Exception:
            app_logger.exception(
                "http.request.failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            reset_request_id(context_token)
            raise

        response.headers["X-Request-ID"] = request_id
        app_logger.info(
            "http.request.completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        reset_request_id(context_token)
        return response

    @app.get("/health", tags=["system"])
    def healthcheck() -> dict[str, str]:
        return {
            "status": "ok",
            "environment": app_settings.app_env,
        }

    app.include_router(create_recommendation_router(recommendation_service))
    app.include_router(create_quote_ingestion_router(quote_ingestion_service))
    app.include_router(create_watch_intent_router(watch_intent_service))
    app.include_router(create_opportunity_router(watch_intent_service))

    if app_settings.app_env == "development":
        from backend.app.api.test_ui_router import create_test_ui_router

        app.include_router(create_test_ui_router())

    return app


app = create_app()
