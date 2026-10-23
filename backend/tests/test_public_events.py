import json
import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.application.watch_intent_service import WatchIntentService
from backend.app.domain.base import DomainModel
from backend.app.domain.models import MarketType, MatchingQuote, Opportunity
from backend.app.domain.public_events import (
    DESTINATION_TEST_V1,
    OPPORTUNITY_IDENTIFIED_V1,
    DestinationTestDataV1,
    OpportunityEventContext,
    OpportunityIdentifiedDataV1,
    PublicEvent,
    build_destination_test_public_event,
    build_opportunity_identified_public_event,
)
from backend.app.engines.opportunity_validity_engine import OpportunityValidityEngine
from backend.app.engines.price_comparison_engine import PriceComparisonService
from backend.app.engines.recommendation_engine import RecommendationEngine
from backend.app.engines.watch_evaluation_engine import WatchEvaluationEngine
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    market_quotes_latest_table,
    markets_table,
    public_events_table,
)
from backend.app.infrastructure.persistence.watch_intent_uow import (
    SqlAlchemyWatchIntentUnitOfWork,
)
from backend.app.infrastructure.publishers.in_memory_publisher import (
    InMemoryWorkflowEventPublisher,
)
from backend.app.infrastructure.quote_provider import FIXTURE_EVENT_ID
from backend.tests.db_helpers import prepare_test_database

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "events"
NOTIFY_CHANNEL = "public_events"


def _validator(event_type: str) -> Draft202012Validator:
    schema = json.loads((CONTRACTS_DIR / f"{event_type}.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _service(session_factory: DatabaseSessionFactory) -> WatchIntentService:
    price_comparison = PriceComparisonService()
    return WatchIntentService(
        unit_of_work_factory=lambda: SqlAlchemyWatchIntentUnitOfWork(session_factory),
        workflow_event_publisher=InMemoryWorkflowEventPublisher(),
        watch_evaluation_engine=WatchEvaluationEngine(
            price_comparison, RecommendationEngine(price_comparison)
        ),
        opportunity_validity_engine=OpportunityValidityEngine(),
        opportunity_ttl_minutes=720,
    )


def _public_event_rows(session_factory: DatabaseSessionFactory) -> list[dict[str, Any]]:
    with session_factory.create_session() as session:
        return [
            dict(row)
            for row in session.execute(select(public_events_table)).mappings().all()
        ]


def _create_fillable_watch(service: WatchIntentService) -> str:
    result = service.create_watch_intent(
        event_id=FIXTURE_EVENT_ID,
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
    )
    assert result.opportunity is not None
    return result.opportunity.id


@pytest.fixture
def opportunity() -> Opportunity:
    return Opportunity(
        id="opp-1",
        watch_intent_id="wi-1",
        event_id="event-1",
        market_id="market-1",
        market_type=MarketType.TOTAL,
        selection="over",
        line=221.5,
        target_price=-110,
        best_sportsbook="FanDuel",
        best_price=-105,
        matching_quotes=[MatchingQuote(sportsbook="FanDuel", price=-105)],
    )


def test_built_event_with_unknown_context_still_validates(opportunity: Opportunity) -> None:
    event = build_opportunity_identified_public_event(
        opportunity=opportunity,
        context=OpportunityEventContext(),
    )

    payload = event.to_cloudevent()

    _validator(OPPORTUNITY_IDENTIFIED_V1).validate(payload)
    assert payload["data"]["best"]["quoted_at"] is None
    assert payload["data"]["event"]["home"] is None


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 10, 18, 15, 30),
        datetime(2026, 10, 18, 15, 30, tzinfo=UTC),
        datetime(2026, 10, 18, 15, 30, tzinfo=timezone(timedelta(hours=-4))),
    ],
)
def test_typed_payload_preserves_wire_shape_and_timestamps(
    opportunity: Opportunity,
    timestamp: datetime,
) -> None:
    event = build_opportunity_identified_public_event(
        opportunity=opportunity,
        context=OpportunityEventContext(
            sport="basketball",
            league="NBA",
            home="Celtics",
            away="Knicks",
            starts_at=timestamp,
            best_quoted_at=timestamp,
        ),
    )

    assert event.data.opportunity_id == opportunity.id
    assert event.data.market_type is MarketType.TOTAL
    assert event.data.best.quoted_at == timestamp
    expected_time = (timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)).isoformat()
    payload = event.to_cloudevent()
    assert payload["data"] == {
        "opportunity_id": "opp-1",
        "watch_intent_id": "wi-1",
        "event": {
            "id": "event-1",
            "sport": "basketball",
            "league": "NBA",
            "home": "Celtics",
            "away": "Knicks",
            "starts_at": expected_time,
        },
        "market_type": "total",
        "selection": "over",
        "line": 221.5,
        "target_price": -110,
        "best": {"sportsbook": "FanDuel", "price": -105, "quoted_at": expected_time},
        "matching": [{"sportsbook": "FanDuel", "price": -105}],
    }
    _validator(OPPORTUNITY_IDENTIFIED_V1).validate(payload)
    restored = PublicEvent[OpportunityIdentifiedDataV1].model_validate(payload)
    assert restored.to_cloudevent() == payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("opportunity_id", ""),
        ("market_type", "unknown"),
        ("target_price", "not odds"),
        ("matching", []),
        ("matching", [{"sportsbook": "FanDuel"}]),
        ("best", {"sportsbook": "FanDuel", "price": -105, "quoted_at": None, "typo": 1}),
        ("typo", "extra field"),
    ],
)
def test_typed_payload_rejects_invalid_contract_data(
    opportunity: Opportunity,
    field: str,
    value: Any,
) -> None:
    event = build_opportunity_identified_public_event(
        opportunity=opportunity,
        context=OpportunityEventContext(),
    )
    payload = event.to_cloudevent()
    payload["data"][field] = value

    with pytest.raises(ValidationError):
        PublicEvent[OpportunityIdentifiedDataV1].model_validate(payload)


def test_payload_serializes_fully_when_held_as_the_generic_bound(
    opportunity: Opportunity,
) -> None:
    # Staging ports hold PublicEvent[DomainModel]. Serialization must follow the
    # payload's runtime type, or an event re-wrapped at the bound would dump `{}`.
    typed = build_opportunity_identified_public_event(
        opportunity=opportunity, context=OpportunityEventContext()
    )
    rewrapped = PublicEvent[DomainModel](**typed.model_dump(exclude={"data"}), data=typed.data)

    assert rewrapped.to_cloudevent() == typed.to_cloudevent()


def test_bare_public_event_is_rejected_with_a_clear_message(
    opportunity: Opportunity,
) -> None:
    payload = build_opportunity_identified_public_event(
        opportunity=opportunity, context=OpportunityEventContext()
    ).to_cloudevent()

    with pytest.raises(TypeError, match="must be parametrized"):
        PublicEvent(**payload)
    with pytest.raises(TypeError, match="must be parametrized"):
        PublicEvent.model_validate(payload)
    # Parametrized at the bound is fine: that is how staging ports hold events.
    assert PublicEvent[OpportunityIdentifiedDataV1].model_validate(payload).id == payload["id"]


def test_triggered_watch_writes_one_public_event_matching_the_contract(
    sqlite_database_url: str,
) -> None:
    session_factory = prepare_test_database(sqlite_database_url, seed_demo=True)

    opportunity_id = _create_fillable_watch(_service(session_factory))

    rows = _public_event_rows(session_factory)
    assert len(rows) == 1
    row = rows[0]
    assert row["type"] == OPPORTUNITY_IDENTIFIED_V1
    assert row["dispatched_at"] is None

    payload = row["payload"]
    _validator(OPPORTUNITY_IDENTIFIED_V1).validate(payload)
    assert payload["id"] == row["id"]
    assert payload["subject"] == opportunity_id
    data = payload["data"]
    assert data["opportunity_id"] == opportunity_id
    event = data["event"]
    assert (event["id"], event["sport"], event["league"]) == (
        FIXTURE_EVENT_ID,
        "basketball",
        "NBA",
    )
    assert (event["home"], event["away"]) == ("Celtics", "Knicks")
    assert event["starts_at"] is not None

    # `quoted_at` is the best book's own line-movement time, not the ingest time.
    with session_factory.create_session() as session:
        stored_quoted_at = session.execute(
            select(market_quotes_latest_table.c.quoted_at)
            .select_from(
                market_quotes_latest_table.join(
                    markets_table,
                    market_quotes_latest_table.c.market_id == markets_table.c.id,
                )
            )
            .where(
                markets_table.c.market_type == MarketType.MONEYLINE.value,
                markets_table.c.selection == "knicks",
                market_quotes_latest_table.c.sportsbook == data["best"]["sportsbook"],
            )
        ).scalar_one()
    published = data["best"]["quoted_at"]
    if stored_quoted_at is None:
        assert published is None
    else:
        assert datetime.fromisoformat(published).replace(tzinfo=None) == (
            stored_quoted_at.replace(tzinfo=None)
        )


def test_rolled_back_trigger_leaves_no_public_event(
    sqlite_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = prepare_test_database(sqlite_database_url, seed_demo=True)

    def fail_after_staging(self: SqlAlchemyWatchIntentUnitOfWork) -> None:
        raise RuntimeError("commit fails after the public event was staged")

    monkeypatch.setattr(
        SqlAlchemyWatchIntentUnitOfWork,
        "_persist_staged_public_events",
        fail_after_staging,
    )

    with pytest.raises(RuntimeError):
        _create_fillable_watch(_service(session_factory))

    monkeypatch.undo()
    assert _public_event_rows(session_factory) == []


def test_postgres_public_event_insert_notifies_listeners_after_commit() -> None:
    database_url = os.environ.get("STAGE2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Postgres integration environment is not configured.")

    session_factory = prepare_test_database(
        database_url, seed_demo=True, drop_existing=True
    )
    try:
        libpq_url = database_url.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(libpq_url, autocommit=True) as listener:
            listener.execute(f"LISTEN {NOTIFY_CHANNEL}")

            _create_fillable_watch(_service(session_factory))

            notifications = list(listener.notifies(timeout=2.0, stop_after=1))

        rows = _public_event_rows(session_factory)
        assert len(rows) == 1
        _validator(OPPORTUNITY_IDENTIFIED_V1).validate(rows[0]["payload"])
        assert [n.payload for n in notifications] == [rows[0]["id"]]
        assert notifications[0].channel == NOTIFY_CHANNEL
    finally:
        session_factory.engine.dispose()


@pytest.mark.parametrize(
    "example",
    sorted((CONTRACTS_DIR / "examples").glob("*.json")),
    ids=lambda path: path.stem,
)
def test_contract_examples_validate_against_their_schema(example: Path) -> None:
    # Go decodes these same examples; both sides agreeing on them is the contract.
    _validator(example.stem).validate(json.loads(example.read_text()))


def test_destination_test_payload_is_typed_and_round_trips() -> None:
    event = build_destination_test_public_event(destination_id="dest-1")

    assert isinstance(event.data, DestinationTestDataV1)
    payload = event.to_cloudevent()
    _validator(DESTINATION_TEST_V1).validate(payload)
    assert payload["subject"] == payload["data"]["destination_id"] == "dest-1"
    assert datetime.fromisoformat(payload["data"]["requested_at"]).tzinfo is not None
    restored = PublicEvent[DestinationTestDataV1].model_validate(payload)
    assert restored.to_cloudevent() == payload


@pytest.mark.parametrize(
    ("field", "value"),
    [("destination_id", ""), ("requested_at", "not a time"), ("typo", "extra field")],
)
def test_destination_test_payload_rejects_invalid_contract_data(
    field: str, value: Any
) -> None:
    payload = build_destination_test_public_event(destination_id="dest-1").to_cloudevent()
    payload["data"][field] = value

    with pytest.raises(ValidationError):
        PublicEvent[DestinationTestDataV1].model_validate(payload)
