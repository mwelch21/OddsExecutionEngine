from pathlib import Path

from alembic import command
from alembic.config import Config

from backend.app.config import Settings


def upgrade_database(database_url: str | None = None) -> None:
    config = _build_alembic_config(database_url)
    command.upgrade(config, "head")


def _build_alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(_alembic_ini_path()))
    target_url = database_url or Settings().database_url
    config.set_main_option("sqlalchemy.url", target_url)
    return config


def _alembic_ini_path() -> Path:
    return Path(__file__).resolve().parents[3] / "db" / "alembic.ini"
