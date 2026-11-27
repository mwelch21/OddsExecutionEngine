from fastapi import APIRouter, HTTPException

from backend.app.api.admin.book_filter_schemas import BookFilterRequest, BookFilterResponse
from backend.app.application.book_filter_service import BookFilterService
from backend.app.domain.book_filter import UnknownSportsbooksError


def create_book_filter_router(service: BookFilterService) -> APIRouter:
    router = APIRouter(tags=["book-filter"])

    @router.get("/book-filter", response_model=BookFilterResponse)
    def get_book_filter() -> BookFilterResponse:
        return BookFilterResponse.from_domain(service.get_status())

    # Only stores the filter: no watch is re-evaluated and no opportunity changes.
    @router.put("/book-filter", response_model=BookFilterResponse)
    def put_book_filter(request: BookFilterRequest) -> BookFilterResponse:
        try:
            status = service.update(request.to_domain())
        except UnknownSportsbooksError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err
        return BookFilterResponse.from_domain(status)

    return router
