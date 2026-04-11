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


def test_settings_reads_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("POSTGRES_DB", "env_markets")
    monkeypatch.setenv("POSTGRES_USER", "env_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "env_password")
    monkeypatch.setenv("POSTGRES_HOST", "env-db")
    monkeypatch.setenv("POSTGRES_PORT", "5434")

    settings = Settings()

    assert settings.app_env == "development"
    assert settings.database_url == "postgresql+psycopg://env_user:env_password@env-db:5434/env_markets"


def test_settings_rejects_default_passwords_in_production() -> None:
    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD must be set"):
        Settings(app_env="production")


def test_settings_rejects_unknown_environment() -> None:
    with pytest.raises(ValidationError, match="development|production"):
        Settings(app_env="staging")  # type: ignore[arg-type]
