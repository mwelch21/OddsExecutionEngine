from fastapi.testclient import TestClient

from backend.app.main import app


def test_healthcheck_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "development",
    }


def test_recommendation_endpoint_returns_fillable_moneyline_result() -> None:
    client = TestClient(app)

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


def test_recommendation_endpoint_returns_nearest_miss_when_unfillable() -> None:
    client = TestClient(app)

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


def test_recommendation_endpoint_returns_empty_result_for_unmatched_line() -> None:
    client = TestClient(app)

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


def test_recommendation_endpoint_validates_total_selection() -> None:
    client = TestClient(app)

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


def test_recommendation_endpoint_validates_moneyline_line_omission() -> None:
    client = TestClient(app)

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
