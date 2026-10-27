"""Service wiring shared by the API and the Auto-Refresh worker.

Both processes must build ingestion identically: the worker refreshes through the
same service, provider settings and watch evaluation as a manual refresh, only
without the HTTP hop (ADR-016).
"""

from backend.app.application.auto_refresh_service import AutoRefreshService
from backend.app.application.ports import QuoteIngestionProvider, WorkflowEventPublisher
from backend.app.application.quote_ingestion_service import QuoteIngestionService
from backend.app.application.watch_intent_service import WatchIntentService
from backend.app.config import Settings
from backend.app.engines.auto_refresh_cadence_engine import AutoRefreshCadenceEngine
from backend.app.engines.normalization_engine import NormalizationEngine
from backend.app.engines.opportunity_validity_engine import OpportunityValidityEngine
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine
from backend.app.infrastructure.caching.in_process_cache import InProcessProviderCache
from backend.app.infrastructure.odds_api_provider import TheOddsApiProvider
from backend.app.infrastructure.persistence.auto_refresh_uow import (
    PostgresAdvisoryCycleLock,
    SqlAlchemyAutoRefreshUnitOfWork,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.quote_ingestion_uow import (
    SqlAlchemyQuoteIngestionUnitOfWork,
)
from backend.app.infrastructure.persistence.watch_intent_uow import (
    SqlAlchemyWatchIntentUnitOfWork,
)
from backend.app.infrastructure.quote_provider import InMemoryQuoteProvider


def build_quote_provider(settings: Settings) -> QuoteIngestionProvider:
    if settings.quote_provider == "odds_api":
        return TheOddsApiProvider(
            api_key=settings.odds_api_key,
            regions=[r.strip() for r in settings.odds_api_regions.split(",")],
            markets=[m.strip() for m in settings.odds_api_markets.split(",")],
            # One cache per provider, living as long as the process. A deliberate
            # refresh still pulls live; this only collapses simultaneous pulls and
            # repeats of incidental reads such as listing a sport's events.
            response_cache=InProcessProviderCache(
                ttl_seconds=settings.provider_cache_ttl_seconds,
            ),
        )
    return InMemoryQuoteProvider()


def build_watch_intent_service(
    settings: Settings,
    session_factory: DatabaseSessionFactory,
    workflow_event_publisher: WorkflowEventPublisher,
    price_comparison_service: PriceComparisonService,
    recommendation_engine: RecommendationEngine,
) -> WatchIntentService:
    return WatchIntentService(
        unit_of_work_factory=lambda: SqlAlchemyWatchIntentUnitOfWork(session_factory),
        workflow_event_publisher=workflow_event_publisher,
        watch_evaluation_engine=WatchEvaluationEngine(
            price_comparison_service,
            recommendation_engine,
        ),
        opportunity_validity_engine=OpportunityValidityEngine(),
        opportunity_ttl_minutes=settings.opportunity_ttl_minutes,
    )


def build_quote_ingestion_service(
    settings: Settings,
    session_factory: DatabaseSessionFactory,
    workflow_event_publisher: WorkflowEventPublisher,
    watch_intent_service: WatchIntentService,
) -> QuoteIngestionService:
    return QuoteIngestionService(
        unit_of_work_factory=lambda: SqlAlchemyQuoteIngestionUnitOfWork(session_factory),
        quote_provider=build_quote_provider(settings),
        normalization_engine=NormalizationEngine(),
        workflow_event_publisher=workflow_event_publisher,
        watch_intent_service=watch_intent_service,
    )


def build_auto_refresh_service(
    session_factory: DatabaseSessionFactory,
    quote_ingestion_service: QuoteIngestionService,
) -> AutoRefreshService:
    return AutoRefreshService(
        unit_of_work_factory=lambda: SqlAlchemyAutoRefreshUnitOfWork(session_factory),
        cycle_lock=PostgresAdvisoryCycleLock(session_factory),
        quote_ingestion_service=quote_ingestion_service,
        cadence_engine=AutoRefreshCadenceEngine(),
    )
