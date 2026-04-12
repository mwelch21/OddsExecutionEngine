from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Odds Execution Engine"
    app_env: Literal["development", "production"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    postgres_db: str = "odds_execution"
    postgres_user: str = "app"
    postgres_password: SecretStr = SecretStr("app")
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    database_url_override: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_security_constraints(self) -> "Settings":
        if self.app_env.lower() != "production":
            return self

        insecure_passwords = {
            "",
            "app",
            "changeme",
            "password",
            "postgres",
            "secret",
        }

        if self.postgres_password.get_secret_value() in insecure_passwords:
            raise ValueError(
                "POSTGRES_PASSWORD must be set to a non-default secret in production."
            )

        return self

    @property
    def database_url(self) -> str:
        if self.database_url_override is not None:
            return self.database_url_override
        return (
            "postgresql+psycopg://"
            f"{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
