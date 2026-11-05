"""Quota observations and the quota warning, against a migrated database (ADR-016)."""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import select

from backend.app.application.quota_service import QuotaService
from backend.app.domain.auto_refresh import AutoRefreshSettings
from backend.app.domain.public_events import QUOTA_WARNING_V1
from backend.app.domain.quota import QuotaReading, QuotaSource
from backend.app.engines.quota_engine import QuotaEngine
from backend.app.infrastructure.persistence.auto_refresh_uow import (
    SqlAlchemyAutoRefreshUnitOfWork,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.quota_uow import SqlAlchemyQuotaUnitOfWork
from backend.app.infrastructure.persistence.schema import public_events_table
from backend.tests.db_helpers import prepare_test_database

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "events"
T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["sqlite", "postgres"])
def session_factory(
    request: pytest.FixtureRequest, sqlite_database_url: str
) -> Iterator[DatabaseSessionFactory]:
    if request.param == "postgres":
        url = os.environ.get("STAGE2_TEST_DATABASE_URL")
        if not url:
            pytest.skip("Postgres integration environment is not configured.")
        factory = prepare_test_database(url, seed_demo=False, drop_existing=True)
    else:
        factory = prepare_test_database(sqlite_database_url, seed_demo=False)
    yield factory
    factory.engine.dispose()


def _service(session_factory: DatabaseSessionFactory) -> QuotaService:
    return QuotaService(
        unit_of_work_factory=lambda: SqlAlchemyQuotaUnitOfWork(session_factory),
        quota_engine=QuotaEngine(),
    )


def _reading(remaining: int | None, used: int | None = None, minute: int = 0) -> QuotaReading:
    return QuotaReading(
        credits_remaining=remaining,
        credits_used=used if used is not None or remaining is None else 500 - remaining,
        estimated_cost=3,
        observed_at=T0 + timedelta(minutes=minute),
    )


def _warnings(session_factory: DatabaseSessionFactory) -> list[dict[str, Any]]:
    with session_factory.create_session() as session:
        rows = session.execute(
            select(public_events_table.c.payload)
            .where(public_events_table.c.type == QUOTA_WARNING_V1)
            .order_by(public_events_table.c.created_at)
        ).scalars()
        return list(rows)


def test_every_reading_is_stored_and_the_latest_is_the_status(
    session_factory: DatabaseSessionFactory,
) -> None:
    service = _service(session_factory)

    service.record(_reading(497, minute=0))
    service.record(_reading(494, minute=5))

    status = service.status()
    assert status.latest is not None
    assert (status.latest.remaining, status.latest.used) == (494, 6)
    assert status.latest.source is QuotaSource.HEADERS
    assert status.floor == 50
    assert status.paused is False


def test_absent_headers_continue_the_count_locally(
    session_factory: DatabaseSessionFactory,
) -> None:
    service = _service(session_factory)

    service.record(_reading(100, used=400))
    service.record(_reading(None, minute=5))

    latest = service.status().latest
    assert latest is not None
    assert (latest.remaining, latest.used, latest.source) == (97, 403, QuotaSource.LOCAL)


def test_crossing_below_the_floor_writes_exactly_one_warning(
    session_factory: DatabaseSessionFactory,
) -> None:
    service = _service(session_factory)

    for minute, remaining in enumerate([53, 50, 47, 44, 41]):
        service.record(_reading(remaining, minute=minute))

    [warning] = _warnings(session_factory)
    assert warning["type"] == QUOTA_WARNING_V1
    assert warning["data"]["remaining"] == 47
    assert warning["data"]["used"] == 453
    assert warning["data"]["floor"] == 50


def test_rising_back_above_the_floor_re_arms_the_warning(
    session_factory: DatabaseSessionFactory,
) -> None:
    service = _service(session_factory)

    for minute, remaining in enumerate([60, 47, 500, 497, 49]):
        service.record(_reading(remaining, minute=minute))

    assert [w["data"]["remaining"] for w in _warnings(session_factory)] == [47, 49]


def test_the_operator_floor_overrides_the_derived_one(
    session_factory: DatabaseSessionFactory,
) -> None:
    with SqlAlchemyAutoRefreshUnitOfWork(session_factory) as uow:
        uow.save_settings(AutoRefreshSettings(quota_floor=100))
    service = _service(session_factory)

    service.record(_reading(101))
    service.record(_reading(99, minute=1))

    assert service.status().floor == 100
    assert [w["data"]["floor"] for w in _warnings(session_factory)] == [100]


def test_out_of_credits_reports_paused(session_factory: DatabaseSessionFactory) -> None:
    service = _service(session_factory)

    service.record(_reading(3, used=497))
    service.record(
        QuotaReading(out_of_credits=True, estimated_cost=3, observed_at=T0 + timedelta(minutes=1))
    )

    status = service.status()
    assert status.paused is True
    assert status.latest is not None and status.latest.remaining == 0


def test_the_warning_matches_its_public_contract(
    session_factory: DatabaseSessionFactory,
) -> None:
    service = _service(session_factory)

    service.record(_reading(10))

    schema = json.loads((CONTRACTS_DIR / f"{QUOTA_WARNING_V1}.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    [warning] = _warnings(session_factory)
    validator.validate(warning)
    assert warning["dataschema"].endswith(f"/{QUOTA_WARNING_V1}.json")
    example = json.loads((CONTRACTS_DIR / "examples" / f"{QUOTA_WARNING_V1}.json").read_text())
    validator.validate(example)
