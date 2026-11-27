"""observed event status and line phase (#38)

`events.status` has existed since 0004 with a default of `upcoming`, but nothing
wrote it. From this revision ingestion writes it from feed presence: `upcoming`,
`live` (started and still offered), or `ended` (started and no longer offered).
A check constraint holds it to those three values. Stored events keep the value
they have: whether an old started event is live or ended was never observed, so
nothing is guessed. The next pull of its sport settles it.

`market_quotes_latest.phase` and `market_quotes_history.phase` say whether each
line was pulled pre-game or while the event was live. Existing rows are
backfilled from the facts they already hold: a line pulled at or after its
event's start came from a feed that still offered the event, which is exactly
what `live` means. Every other row is `pre_game`.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261127_0018"
down_revision = "20261109_0017"
branch_labels = None
depends_on = None

QUOTE_TABLES = ("market_quotes_latest", "market_quotes_history")


def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.create_check_constraint(
            "ck_events_status", "status IN ('upcoming', 'live', 'ended')"
        )

    for table in QUOTE_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "phase", sa.String(length=16), nullable=False, server_default="pre_game"
                )
            )
            batch_op.create_check_constraint(
                f"ck_{table}_phase", "phase IN ('pre_game', 'live')"
            )
        op.execute(
            f"UPDATE {table} SET phase = 'live' WHERE ingested_at >= ("  # noqa: S608
            "SELECT events.starts_at FROM markets JOIN events ON events.id = markets.event_id"
            f" WHERE markets.id = {table}.market_id)"
        )


def downgrade() -> None:
    for table in QUOTE_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(f"ck_{table}_phase", type_="check")
            batch_op.drop_column("phase")
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_constraint("ck_events_status", type_="check")
