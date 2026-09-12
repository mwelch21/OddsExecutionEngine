import pytest
from pydantic import SecretStr, ValidationError

from backend.app.config import Settings


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


def test_opportunity_ttl_default_suits_manual_refresh() -> None:
    """Nothing refreshes on a schedule yet, so a minutes-long TTL made every
    opportunity read invalid before a human could look at it."""
    assert Settings().opportunity_ttl_minutes == 720


def test_opportunity_ttl_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPPORTUNITY_TTL_MINUTES", "15")

    assert Settings().opportunity_ttl_minutes == 15


def test_provider_cache_ttl_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().provider_cache_ttl_seconds == 300

    monkeypatch.setenv("PROVIDER_CACHE_TTL_SECONDS", "30")

    assert Settings().provider_cache_ttl_seconds == 30


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("OPPORTUNITY_TTL_MINUTES", "0"),
        ("PROVIDER_CACHE_TTL_SECONDS", "-1"),
    ],
)
def test_non_positive_ttls_are_rejected(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError):
        Settings()
