from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.app.api.admin import require_operator
from backend.app.config import Settings
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database


def _deny_operator() -> None:
    raise HTTPException(status_code=403, detail="operator only")


def test_admin_routes_are_open_while_the_operator_hook_is_a_no_op(
    sqlite_database_url: str,
) -> None:
    prepare_test_database(sqlite_database_url, seed_demo=False)
    with TestClient(create_app(Settings(database_url_override=sqlite_database_url))) as client:
        response = client.get("/api/v1/admin/auto-refresh")

    assert response.status_code == 200


def test_the_operator_hook_gates_every_admin_route_and_nothing_else(
    sqlite_database_url: str,
) -> None:
    prepare_test_database(sqlite_database_url, seed_demo=False)
    app = create_app(Settings(database_url_override=sqlite_database_url))
    # Auth (#14) replaces the no-op; this stands in for a caller who is not the operator.
    app.dependency_overrides[require_operator] = _deny_operator

    with TestClient(app) as client:
        admin_get = client.get("/api/v1/admin/auto-refresh")
        admin_put = client.put(
            "/api/v1/admin/auto-refresh", json={"enabled": True, "interval_minutes": 5}
        )
        public = client.get("/api/v1/sports")

    assert admin_get.status_code == 403
    assert admin_put.status_code == 403
    assert public.status_code == 200


def test_every_admin_route_carries_the_operator_hook(sqlite_database_url: str) -> None:
    app = create_app(Settings(database_url_override=sqlite_database_url))

    admin_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/admin/")
    ]

    assert admin_routes
    for route in admin_routes:
        hooks = [dependency.call for dependency in route.dependant.dependencies]
        assert require_operator in hooks, route.path


def test_auto_refresh_is_gone_from_its_old_path(sqlite_database_url: str) -> None:
    with TestClient(create_app(Settings(database_url_override=sqlite_database_url))) as client:
        response = client.get("/api/v1/auto-refresh")

    assert response.status_code == 404
