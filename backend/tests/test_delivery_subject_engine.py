import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.domain.public_events import (
    DESTINATION_TEST_V1,
    OPPORTUNITY_IDENTIFIED_V1,
    QUOTA_WARNING_V1,
)
from backend.app.engines.delivery_subject_engine import DeliverySubjectEngine

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "contracts" / "events" / "examples"


def _example_data(event_type: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((EXAMPLES_DIR / f"{event_type}.json").read_text())["data"]
    return data


def test_opportunity_subject_names_the_matchup_selection_and_best_price() -> None:
    subject = DeliverySubjectEngine().subject_for(
        OPPORTUNITY_IDENTIFIED_V1, _example_data(OPPORTUNITY_IDENTIFIED_V1)
    )

    assert subject == "Knicks @ Celtics · Knicks +125 @ DraftKings"


def test_opportunity_subject_shows_a_signed_spread_line() -> None:
    data = _example_data(OPPORTUNITY_IDENTIFIED_V1) | {
        "market_type": "spread",
        "selection": "montréal canadiens",
        "line": 1.5,
    }
    data["best"] = {"sportsbook": "FanDuel", "price": -110}

    subject = DeliverySubjectEngine().subject_for(OPPORTUNITY_IDENTIFIED_V1, data)

    assert subject == "Knicks @ Celtics · Montréal Canadiens +1.5 -110 @ FanDuel"


def test_test_and_quota_warning_subjects() -> None:
    engine = DeliverySubjectEngine()

    assert engine.subject_for(DESTINATION_TEST_V1, _example_data(DESTINATION_TEST_V1)) == (
        "Test notification"
    )
    assert engine.subject_for(QUOTA_WARNING_V1, _example_data(QUOTA_WARNING_V1)) == (
        "Credits running low · 47 left"
    )


@pytest.mark.parametrize(
    ("event_type", "data"),
    [
        ("oddsengine.something.new.v1", {"secret": "x"}),
        (OPPORTUNITY_IDENTIFIED_V1, {"selection": 7}),
        (QUOTA_WARNING_V1, {}),
    ],
)
def test_an_unknown_or_unreadable_event_falls_back_to_its_type(
    event_type: str, data: dict[str, Any]
) -> None:
    assert DeliverySubjectEngine().subject_for(event_type, data) == event_type
