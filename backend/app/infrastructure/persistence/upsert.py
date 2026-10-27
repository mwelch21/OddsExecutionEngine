from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session


def upsert(
    session: Session,
    table: Table,
    values: Mapping[str, Any],
    key_columns: Sequence[str],
) -> None:
    """Insert a row, or update every non-key column of the one already there.

    One statement, so two writers racing on an absent row cannot both insert.
    """
    if session.bind is None:
        raise RuntimeError("Upsert session is not bound to an engine.")
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        pg_statement = postgresql_insert(table).values(**values)
        session.execute(
            pg_statement.on_conflict_do_update(
                index_elements=list(key_columns),
                set_={
                    name: pg_statement.excluded[name]
                    for name in values
                    if name not in key_columns
                },
            )
        )
        return
    if dialect == "sqlite":
        sqlite_statement = sqlite_insert(table).values(**values)
        session.execute(
            sqlite_statement.on_conflict_do_update(
                index_elements=list(key_columns),
                set_={
                    name: sqlite_statement.excluded[name]
                    for name in values
                    if name not in key_columns
                },
            )
        )
        return
    raise RuntimeError(f"Unsupported dialect for upsert: {dialect}")
