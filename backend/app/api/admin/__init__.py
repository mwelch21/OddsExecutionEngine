"""Operator routes for the Admin view, all under `/api/v1/admin` (ADR-018).

Each feature keeps its own router and schema modules in this package. `main.py`
includes each feature's router into the one `create_admin_router()` returns, so
every admin route carries the operator hook.
"""

from fastapi import APIRouter, Depends

from backend.app.api.admin.operator import require_operator


def create_admin_router() -> APIRouter:
    return APIRouter(prefix="/admin", dependencies=[Depends(require_operator)])


__all__ = ["create_admin_router", "require_operator"]
