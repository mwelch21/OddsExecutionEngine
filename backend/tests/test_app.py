import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from backend.app.config import Settings
from backend.app.infrastructure.persistence.commands import odds_db_seed_demo_main
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    events_table,
    execution_recommendations_table,
    market_quotes_history_table,
    market_quotes_latest_table,
    markets_table,
    order_intents_table,
)
from backend.app.infrastructure.persistence.seed import truncate_application_tables
from backend.app.main import create_app
from backend.tests.db_helpers import prepare_test_database


def test_healthcheck_returns_ok(sqlite_database_url: str) -> None:
    with TestClient(_build_test_app(sqlite_database_url)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "development",
    }


def test_recommendation_endpoint_returns_fillable_moneyline_result(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_test_app(sqlite_database_url)) as client:
        response = client.post(
            "/execution/recommendation",
            json={
                "event_id": "nba-knicks-celtics-2026-04-11",
                "market_type": "moneyline",
                "selection": "knicks",
                "target_price": 121,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "request": {
            "event_id": "nba-knicks-celtics-2026-04-11",
            "market_type": "moneyline",
            "selection": "knicks",
            "line": None,
            "target_price": 121,
        },
        "fillable": True,
        "best_quote": {
            "sportsbook": "DraftKings",
            "selection": "knicks",
            "price": 125,
            "line": None,
        },
        "ranked_quotes": [
            {
                "sportsbook": "DraftKings",
                "selection": "knicks",
                "price": 125,
                "line": None,
            },
            {
                "sportsbook": "FanDuel",
                "selection": "knicks",
                "price": 125,
                "line": None,
            },
            {
                "sportsbook": "BetMGM",
                "selection": "knicks",
                "price": 120,
                "line": None,
            },
        ],
        "nearest_miss": None,
        "matched_quote_count": 3,
    }


def test_recommendation_endpoint_returns_nearest_miss_when_unfillable(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_test_app(sqlite_database_url)) as client:
        response = client.post(
            "/execution/recommendation",
            json={
                "event_id": "nba-knicks-celtics-2026-04-11",
                "market_type": "total",
                "selection": "over",
                "line": 221.5,
                "target_price": -105,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "request": {
            "event_id": "nba-knicks-celtics-2026-04-11",
            "market_type": "total",
            "selection": "over",
            "line": 221.5,
            "target_price": -105,
        },
        "fillable": False,
        "best_quote": {
            "sportsbook": "FanDuel",
            "selection": "over",
            "price": -108,
            "line": 221.5,
        },
        "ranked_quotes": [
            {
                "sportsbook": "FanDuel",
                "selection": "over",
                "price": -108,
                "line": 221.5,
            },
            {
                "sportsbook": "DraftKings",
                "selection": "over",
                "price": -112,
                "line": 221.5,
            },
        ],
        "nearest_miss": {
            "sportsbook": "FanDuel",
            "selection": "over",
            "price": -108,
            "line": 221.5,
        },
        "matched_quote_count": 2,
    }


def test_recommendation_endpoint_returns_empty_result_for_unmatched_line(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_test_app(sqlite_database_url)) as client:
        response = client.post(
            "/execution/recommendation",
            json={
                "event_id": "nba-knicks-celtics-2026-04-11",
                "market_type": "spread",
                "selection": "knicks",
                "line": 6.5,
                "target_price": -110,
            },
        )

    assert response.status_code == 200
    assert response.json()["fillable"] is False
    assert response.json()["best_quote"] is None
    assert response.json()["nearest_miss"] is None
    assert response.json()["ranked_quotes"] == []
    assert response.json()["matched_quote_count"] == 0


def test_recommendation_endpoint_validates_total_selection(sqlite_database_url: str) -> None:
    with TestClient(_build_test_app(sqlite_database_url)) as client:
        response = client.post(
            "/execution/recommendation",
            json={
                "event_id": "nba-knicks-celtics-2026-04-11",
                "market_type": "total",
                "selection": "knicks",
                "line": 221.5,
                "target_price": -110,
            },
        )

    assert response.status_code == 422


def test_recommendation_endpoint_validates_moneyline_line_omission(
    sqlite_database_url: str,
) -> None:
    with TestClient(_build_test_app(sqlite_database_url)) as client:
        response = client.post(
            "/execution/recommendation",
            json={
                "event_id": "nba-knicks-celtics-2026-04-11",
                "market_type": "moneyline",
                "selection": "knicks",
                "line": 1.5,
                "target_price": 120,
            },
        )

    assert response.status_code == 422


def test_recommendation_endpoint_persists_order_intent_and_recommendation(
    sqlite_database_url: str,
) -> None:
    app = _build_test_app(sqlite_database_url)

    with TestClient(app) as client:
        response = client.post(
            "/execution/recommendation",
            json={
                "event_id": "nba-knicks-celtics-2026-04-11",
                "market_type": "moneyline",
                "selection": "knicks",
                "target_price": 121,
            },
        )

    assert response.status_code == 200

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    with session_factory.create_session() as session:
        stored_intent = session.execute(select(order_intents_table)).mappings().one()
        stored_recommendation = (
            session.execute(select(execution_recommendations_table)).mappings().one()
        )

    assert stored_intent["event_external_id"] == "nba-knicks-celtics-2026-04-11"
    assert stored_intent["market_type"] == "moneyline"
    assert stored_intent["selection"] == "knicks"
    assert stored_intent["target_price"] == 121
    assert stored_recommendation["fillable"] is True
    assert stored_recommendation["matched_quote_count"] == 3
    assert stored_recommendation["best_quote"]["sportsbook"] == "DraftKings"
    assert len(stored_recommendation["ranked_quotes"]) == 3


def test_sqlite_smoke_setup_populates_demo_quotes_for_local_convenience(
    sqlite_database_url: str,
) -> None:
    prepare_test_database(sqlite_database_url, seed_demo=True)

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    with session_factory.create_session() as session:
        history_count = session.execute(select(market_quotes_history_table.c.id)).all()

    assert len(history_count) == 10


def test_app_startup_does_not_create_schema(sqlite_database_url: str) -> None:
    app = create_app(Settings(database_url_override=sqlite_database_url))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200

    inspector = inspect(DatabaseSessionFactory(sqlite_database_url).engine)
    assert inspector.get_table_names() == []


def test_explicit_migration_path_creates_expected_tables(sqlite_database_url: str) -> None:
    session_factory = prepare_test_database(sqlite_database_url, seed_demo=False)

    inspector = inspect(session_factory.engine)

    assert sorted(inspector.get_table_names()) == [
        "alembic_version",
        "events",
        "execution_recommendations",
        "market_quotes_history",
        "market_quotes_latest",
        "markets",
        "order_intents",
    ]


def test_seed_demo_cli_populates_expected_quote_tables(
    sqlite_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_test_database(sqlite_database_url, seed_demo=False)
    monkeypatch.setenv("DATABASE_URL_OVERRIDE", sqlite_database_url)

    odds_db_seed_demo_main()

    session_factory = DatabaseSessionFactory(sqlite_database_url)
    with session_factory.create_session() as session:
        latest_count = session.execute(select(market_quotes_latest_table)).all()
        history_count = session.execute(select(market_quotes_history_table)).all()
        event_count = session.execute(select(events_table)).all()
        market_count = session.execute(select(markets_table)).all()

    assert len(latest_count) == 10
    assert len(history_count) == 10
    assert len(event_count) == 1
    assert len(market_count) == 6


def test_postgres_is_required_truth_path_for_persistence_correctness() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    session_factory = prepare_test_database(database_url, seed_demo=True, drop_existing=True)
    app = create_app(Settings(database_url_override=database_url))

    try:
        with TestClient(app) as client:
            response = client.post(
                "/execution/recommendation",
                json={
                    "event_id": "nba-knicks-celtics-2026-04-11",
                    "market_type": "moneyline",
                    "selection": "knicks",
                    "target_price": 121,
                },
            )

        assert response.status_code == 200

        with session_factory.create_session() as session:
            stored_intent = session.execute(select(order_intents_table)).mappings().all()
            stored_recommendations = session.execute(
                select(execution_recommendations_table)
            ).mappings().all()

        assert len(stored_intent) == 1
        assert len(stored_recommendations) == 1
        assert stored_recommendations[0]["best_quote"]["sportsbook"] == "DraftKings"
    finally:
        truncate_application_tables(session_factory)


def _build_test_app(database_url: str) -> FastAPI:
    prepare_test_database(database_url, seed_demo=True)
    settings = Settings(database_url_override=database_url)
    return create_app(settings)
