from fastapi import APIRouter, Query

from backend.app.api.admin.deliveries_schemas import DeliveryListResponse
from backend.app.application.delivery_query_service import DeliveryQueryService
from backend.app.domain.deliveries import DeliveryFilter, DeliveryStatus

STATUS_QUERY = Query(default=None, description="Only deliveries in this status.")
EVENT_TYPE_QUERY = Query(
    default=None, description="Exact public event type, e.g. oddsengine.quota.warning.v1."
)
DESTINATION_ID_QUERY = Query(default=None, description="Only deliveries to this destination.")
PAGE_QUERY = Query(default=1, ge=1)
PAGE_SIZE_QUERY = Query(default=50, ge=1, le=200)


def create_deliveries_router(service: DeliveryQueryService) -> APIRouter:
    router = APIRouter(tags=["deliveries"])

    @router.get("/deliveries", response_model=DeliveryListResponse)
    def list_deliveries(
        status: DeliveryStatus | None = STATUS_QUERY,
        event_type: str | None = EVENT_TYPE_QUERY,
        destination_id: str | None = DESTINATION_ID_QUERY,
        page: int = PAGE_QUERY,
        page_size: int = PAGE_SIZE_QUERY,
    ) -> DeliveryListResponse:
        return DeliveryListResponse.from_domain(
            service.list_deliveries(
                DeliveryFilter(
                    status=status, event_type=event_type, destination_id=destination_id
                ),
                page=page,
                page_size=page_size,
            )
        )

    return router
