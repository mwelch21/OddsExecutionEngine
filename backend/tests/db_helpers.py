from sqlalchemy import inspect

from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.migrations import upgrade_database
from backend.app.infrastructure.persistence.seed import (
    seed_demo_quotes,
    truncate_application_tables,
)


def prepare_test_database(
    database_url: str,
    *,
    seed_demo: bool,
    drop_existing: bool = False,
) -> DatabaseSessionFactory:
    session_factory = DatabaseSessionFactory(database_url)
    if drop_existing:
        inspector = inspect(session_factory.engine)
        existing_tables = inspector.get_table_names()
        if existing_tables:
            with session_factory.engine.begin() as connection:
                for table_name in reversed(existing_tables):
                    connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table_name} CASCADE")

    upgrade_database(database_url)
    truncate_application_tables(session_factory)
    if seed_demo:
        seed_demo_quotes(session_factory)
    return session_factory
