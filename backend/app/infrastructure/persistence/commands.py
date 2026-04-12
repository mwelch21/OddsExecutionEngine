from backend.app.config import Settings
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.migrations import upgrade_database
from backend.app.infrastructure.persistence.seed import seed_demo_quotes


def odds_db_upgrade_main() -> None:
    upgrade_database()


def odds_db_seed_demo_main() -> None:
    settings = Settings()
    session_factory = DatabaseSessionFactory(settings.database_url)
    seed_demo_quotes(session_factory)
