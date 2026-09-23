"""split quote time into ingest time and the book's own quote time

`quoted_at` used to hold one conflated fact: the moment ingestion pulled the row.
A line the book had not touched in three days therefore read as seconds old.

After this migration the two facts are separate:

- `ingested_at` — when we pulled the quote. Always known, so NOT NULL.
- `quoted_at` — when the sportsbook itself last moved the line, as reported by the
  provider. Providers that expose no such time leave it NULL, which readers treat
  as unknown age rather than freshly moved.

Existing rows are backfilled by moving their old `quoted_at` into `ingested_at` and
nulling `quoted_at`: the stored value was always a pull time, and leaving it in place
would assert a line movement that was never observed.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260912_0008"
down_revision = "20260515_0007"
branch_labels = None
depends_on = None

QUOTE_TABLES = ("market_quotes_latest", "market_quotes_history")


def upgrade() -> None:
    for table in QUOTE_TABLES:
        op.add_column(
            table,
            sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute(f"UPDATE {table} SET ingested_at = quoted_at")  # noqa: S608
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                "ingested_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
            batch_op.alter_column(
                "quoted_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=True,
                server_default=None,
            )
        # Only once quoted_at is nullable: the old value was a pull time, not a
        # line movement, so it cannot stay in a column that now means line movement.
        op.execute(f"UPDATE {table} SET quoted_at = NULL")  # noqa: S608


def downgrade() -> None:
    for table in QUOTE_TABLES:
        # Reverting collapses the two facts back into one. The pull time is the value
        # the old column carried, so it is what goes back.
        op.execute(f"UPDATE {table} SET quoted_at = ingested_at")  # noqa: S608
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                "quoted_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        op.drop_column(table, "ingested_at")
