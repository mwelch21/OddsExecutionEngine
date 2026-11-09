import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request, Response

from backend.app.api.admin import create_admin_router
from backend.app.api.admin.auto_refresh_router import create_auto_refresh_router
from backend.app.api.admin.credit_burn_router import create_credit_burn_router
from backend.app.api.admin.deliveries_router import create_deliveries_router
from backend.app.api.admin.quota_history_router import create_quota_history_router
from backend.app.api.admin.refreshes_router import create_refreshes_router
from backend.app.api.destination_router import create_destination_router
from backend.app.api.event_router import create_event_router
from backend.app.api.opportunity_router import create_opportunity_router
from backend.app.api.quote_ingestion_router import create_quote_ingestion_router
from backend.app.api.recommendation_router import create_recommendation_router
from backend.app.api.watch_intent_router import create_watch_intent_router
from backend.app.application.admin_query_service import AdminQueryService
from backend.app.application.credit_query_service import CreditQueryService
from backend.app.application.delivery_query_service import DeliveryQueryService
from backend.app.application.destination_service import DestinationService
from backend.app.application.event_query_service import EventQueryService
from backend.app.application.recommendation_service import RecommendationService
from backend.app.composition import (
    build_auto_refresh_service,
    build_quota_service,
    build_quote_ingestion_service,
    build_watch_intent_service,
)
from backend.app.config import Settings, get_settings
from backend.app.engines.credit_history_engine import CreditHistoryEngine
from backend.app.engines.delivery_error_engine import DeliveryErrorEngine
from backend.app.engines.delivery_subject_engine import DeliverySubjectEngine
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.quote_matching_engine import QuoteMatchingEngine
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.infrastructure.observability.logging import configure_logging
from backend.app.infrastructure.observability.request_context import (
    reset_request_id,
    set_request_id,
)
from backend.app.infrastructure.persistence.admin_read_uow import (
    SqlAlchemyAdminReadUnitOfWork,
)
from backend.app.infrastructure.persistence.credit_read_uow import SqlAlchemyCreditReadUnitOfWork
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.delivery_read_uow import (
    SqlAlchemyDeliveryReadUnitOfWork,
)
from backend.app.infrastructure.persistence.destination_uow import (
    SqlAlchemyDestinationUnitOfWork,
)
from backend.app.infrastructure.persistence.event_read_uow import (
    SqlAlchemyEventReadUnitOfWork,
)
from backend.app.infrastructure.persistence.recommendation_uow import (
    SqlAlchemyRecommendationUnitOfWork,
)
from backend.app.infrastructure.publishers.logging_publisher import (
    LoggingWorkflowEventPublisher,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings)
    session_factory = DatabaseSessionFactory(app_settings.database_url)
    # ADR-018: the docs and schema live under the versioned path too, so the
    # /api proxy reaches them.
    app = FastAPI(
        title=app_settings.app_name,
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
        openapi_url="/api/v1/openapi.json",
        swagger_ui_oauth2_redirect_url="/api/v1/docs/oauth2-redirect",
    )
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
    watch_intent_service = build_watch_intent_service(
        app_settings,
        session_factory,
        workflow_event_publisher,
        price_comparison_service,
        recommendation_engine,
    )
    event_query_service = EventQueryService(
        unit_of_work_factory=lambda: SqlAlchemyEventReadUnitOfWork(session_factory),
        recommendation_engine=recommendation_engine,
    )
    destination_service = DestinationService(
        unit_of_work_factory=lambda: SqlAlchemyDestinationUnitOfWork(session_factory),
    )
    delivery_query_service = DeliveryQueryService(
        unit_of_work_factory=lambda: SqlAlchemyDeliveryReadUnitOfWork(session_factory),
        subject_engine=DeliverySubjectEngine(),
        error_engine=DeliveryErrorEngine(),
    )
    quota_service = build_quota_service(session_factory)
    quote_ingestion_service = build_quote_ingestion_service(
        app_settings,
        session_factory,
        workflow_event_publisher,
        watch_intent_service,
        quota_service,
    )
    auto_refresh_service = build_auto_refresh_service(
        session_factory, quote_ingestion_service, quota_service
    )
    admin_query_service = AdminQueryService(
        unit_of_work_factory=lambda: SqlAlchemyAdminReadUnitOfWork(session_factory),
    )
    credit_query_service = CreditQueryService(
        unit_of_work_factory=lambda: SqlAlchemyCreditReadUnitOfWork(session_factory),
        history_engine=CreditHistoryEngine(),
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

    # ADR-018: one versioned path for the whole contract. Health is an ops probe,
    # not contract, so it sits under /api but outside the version.
    @app.get("/api/health", tags=["system"])
    def healthcheck() -> dict[str, str]:
        return {
            "status": "ok",
            "environment": app_settings.app_env,
        }

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(create_recommendation_router(recommendation_service))
    api_v1.include_router(create_quote_ingestion_router(quote_ingestion_service))
    api_v1.include_router(create_watch_intent_router(watch_intent_service))
    api_v1.include_router(create_opportunity_router(watch_intent_service))
    api_v1.include_router(create_event_router(event_query_service))
    api_v1.include_router(
        create_destination_router(destination_service, app_settings.vapid_public_key)
    )

    # Admin view routes: one include per feature, all behind the operator hook.
    # Add features before `admin` joins api_v1: include_router copies routes once.
    admin = create_admin_router()
    admin.include_router(create_auto_refresh_router(auto_refresh_service))
    admin.include_router(create_refreshes_router(admin_query_service))
    admin.include_router(create_deliveries_router(delivery_query_service))
    admin.include_router(create_quota_history_router(credit_query_service))
    admin.include_router(create_credit_burn_router(credit_query_service))
    api_v1.include_router(admin)

    if app_settings.app_env == "development":
        from backend.app.api.test_ui_router import create_test_ui_router

        api_v1.include_router(create_test_ui_router())

    app.include_router(api_v1)

    return app


app = create_app()
