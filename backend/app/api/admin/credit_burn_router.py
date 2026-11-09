from fastapi import APIRouter, Query

from backend.app.api.admin.credit_burn_schemas import CreditBurnResponse
from backend.app.application.credit_query_service import CreditQueryService

MONTH_QUERY = Query(
    default=None,
    pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    description="UTC calendar month, YYYY-MM. Defaults to the current month.",
)


def create_credit_burn_router(service: CreditQueryService) -> APIRouter:
    router = APIRouter(tags=["admin"])

    @router.get("/credit-burn", response_model=CreditBurnResponse)
    def get_credit_burn(month: str | None = MONTH_QUERY) -> CreditBurnResponse:
        return CreditBurnResponse.from_domain(service.credit_burn(month))

    return router
