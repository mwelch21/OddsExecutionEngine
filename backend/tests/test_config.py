from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr, ValidationError

from backend.app.config import Settings
from backend.app.domain.models import MarketType, MatchingQuote, Opportunity
from backend.app.engines.opportunity_validity_engine import OpportunityValidityEngine


def test_settings_builds_database_url() -> None:
    settings = Settings(
        postgres_user="user",
        postgres_password=SecretStr("password"),
        postgres_host="db",
        postgres_port=5433,
        postgres_db="markets",
    )

    assert settings.database_url == "postgresql+psycopg://user:password@db:5433/markets"


def test_settings_prefers_database_url_override() -> None:
    settings = Settings(database_url_override="sqlite+pysqlite:////tmp/override.db")

    assert settings.database_url == "sqlite+pysqlite:////tmp/override.db"


def test_settings_does_not_expose_seed_toggle() -> None:
    settings = Settings()

    assert "seed_demo_data" not in settings.model_dump()


def test_settings_reads_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("POSTGRES_DB", "env_markets")
    monkeypatch.setenv("POSTGRES_USER", "env_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "env_password")
    monkeypatch.setenv("POSTGRES_HOST", "env-db")
    monkeypatch.setenv("POSTGRES_PORT", "5434")

    settings = Settings()

    assert settings.app_env == "development"
    assert settings.log_level == "DEBUG"
    assert settings.database_url == "postgresql+psycopg://env_user:env_password@env-db:5434/env_markets"


def test_settings_rejects_default_passwords_in_production() -> None:
    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD must be set"):
        Settings(app_env="production")


def test_settings_rejects_unknown_environment() -> None:
    with pytest.raises(ValidationError, match="development|production"):
        Settings(app_env="staging")  # type: ignore[arg-type]


def test_opportunity_found_earlier_today_is_still_valid_under_the_default_ttl() -> None:
    """Nothing refreshes on a schedule yet, so a minutes-long TTL marked every
    opportunity invalid before a human could look at it."""
    now = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)
    opportunity = _opportunity(created_at=now - timedelta(hours=6))

    result = OpportunityValidityEngine().check_validity(
        opportunity,
        latest_quote_time=opportunity.created_at,
        ttl_minutes=Settings().opportunity_ttl_minutes,
        now=now,
    )

    assert result.is_valid is True


def _opportunity(created_at: datetime) -> Opportunity:
    return Opportunity(
        id="opp-1",
        watch_intent_id="wi-1",
        event_id="event-1",
        market_id="market-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
        best_sportsbook="DraftKings",
        best_price=125,
        matching_quotes=[MatchingQuote(sportsbook="DraftKings", price=125)],
        created_at=created_at,
    )


def test_opportunity_ttl_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPPORTUNITY_TTL_MINUTES", "15")

    assert Settings().opportunity_ttl_minutes == 15


def test_provider_cache_ttl_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().provider_cache_ttl_seconds == 300

    monkeypatch.setenv("PROVIDER_CACHE_TTL_SECONDS", "30")

    assert Settings().provider_cache_ttl_seconds == 30


@pytest.mark.parametrize(
    "variable",
    ["OPPORTUNITY_TTL_MINUTES", "PROVIDER_CACHE_TTL_SECONDS"],
)
def test_negative_ttls_are_rejected(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "-1")

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "variable",
    ["OPPORTUNITY_TTL_MINUTES", "PROVIDER_CACHE_TTL_SECONDS"],
)
def test_zero_ttls_remain_accepted(monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
    """Zero was a usable setting before this change — expire on sight, cache nothing.
    Raising the default must not take a previously valid configuration away."""
    monkeypatch.setenv(variable, "0")

    assert Settings().model_dump()[variable.lower()] == 0
