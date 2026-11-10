from fastapi import APIRouter, HTTPException, Query

from backend.app.api.admin.credit_burn_schemas import CreditBurnResponse
from backend.app.application.credit_query_service import CreditQueryService
from backend.app.engines.credit_history_engine import InvalidMonthError

MONTH_QUERY = Query(
    default=None,
    pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    description="UTC calendar month, YYYY-MM. Defaults to the current month.",
)


def create_credit_burn_router(service: CreditQueryService) -> APIRouter:
    router = APIRouter(tags=["admin"])

    @router.get("/credit-burn", response_model=CreditBurnResponse)
    def get_credit_burn(month: str | None = MONTH_QUERY) -> CreditBurnResponse:
        try:
            burn = service.credit_burn(month)
        except InvalidMonthError as err:
            # The pattern admits months a calendar cannot hold (0000-01, 9999-12).
            raise HTTPException(status_code=422, detail=str(err)) from err
        return CreditBurnResponse.from_domain(burn)

    return router
