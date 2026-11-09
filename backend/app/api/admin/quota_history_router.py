from fastapi import APIRouter, Query

from backend.app.api.admin.quota_history_schemas import QuotaHistoryResponse
from backend.app.application.credit_query_service import CreditQueryService
from backend.app.domain.credits import MAX_HISTORY_DAYS

DAYS_QUERY = Query(default=MAX_HISTORY_DAYS, ge=1, le=MAX_HISTORY_DAYS)


def create_quota_history_router(service: CreditQueryService) -> APIRouter:
    router = APIRouter(tags=["admin"])

    # Unpaged: at most 30 days of hourly buckets, 720 points.
    @router.get("/quota-history", response_model=QuotaHistoryResponse)
    def get_quota_history(days: int = DAYS_QUERY) -> QuotaHistoryResponse:
        return QuotaHistoryResponse.from_domain(days, service.quota_history(days))

    return router
