"""watch window, expiry reason, and opportunity phase (#10, ADR-017)

`watch_intents.watch_window` says which lines a watch may fill on: `pre_game`,
`live` or `full_game`. Existing watches get `pre_game`, which is what they did
before live lines could fill. The column keeps no server default once
backfilled: `WatchWindowPolicy` is the only place a default lives, so every
insert names its window.

`watch_intents.expired_reason` says why an expired watch expired: `ttl`,
`event_started`, `event_ended` or `event_cancelled`. Before this revision only a
TTL could expire a watch, so every stored expired watch is backfilled `ttl`. A
check constraint holds the reason to expired watches only.

`opportunities.phase` is the phase of the best book's line when the
opportunity was identified. Existing rows are backfilled with the rule 0018
used for quotes: an opportunity created at or after its event's start filled
on a live line.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261127_0019"
down_revision = "20261127_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("watch_intents") as batch_op:
        batch_op.add_column(
            sa.Column(
                "watch_window", sa.String(length=16), nullable=False, server_default="pre_game"
            )
        )
        batch_op.add_column(sa.Column("expired_reason", sa.String(length=32), nullable=True))
    op.execute("UPDATE watch_intents SET expired_reason = 'ttl' WHERE status = 'expired'")
    with op.batch_alter_table("watch_intents") as batch_op:
        batch_op.alter_column("watch_window", server_default=None)
        batch_op.create_check_constraint(
            "ck_watch_intents_watch_window",
            "watch_window IN ('pre_game', 'live', 'full_game')",
        )
        batch_op.create_check_constraint(
            "ck_watch_intents_expired_reason",
            "expired_reason IN ('ttl', 'event_started', 'event_ended', 'event_cancelled')",
        )
        batch_op.create_check_constraint(
            "ck_watch_intents_expired_reason_status",
            "(status = 'expired' AND expired_reason IS NOT NULL)"
            " OR (status <> 'expired' AND expired_reason IS NULL)",
        )

    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.add_column(
            sa.Column("phase", sa.String(length=16), nullable=False, server_default="pre_game")
        )
        batch_op.create_check_constraint(
            "ck_opportunities_phase", "phase IN ('pre_game', 'live')"
        )
    op.execute(
        "UPDATE opportunities SET phase = 'live' WHERE created_at >= ("
        "SELECT events.starts_at FROM events"
        " WHERE events.external_id = opportunities.event_external_id)"
    )


def downgrade() -> None:
    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.drop_constraint("ck_opportunities_phase", type_="check")
        batch_op.drop_column("phase")
    with op.batch_alter_table("watch_intents") as batch_op:
        batch_op.drop_constraint("ck_watch_intents_expired_reason_status", type_="check")
        batch_op.drop_constraint("ck_watch_intents_expired_reason", type_="check")
        batch_op.drop_constraint("ck_watch_intents_watch_window", type_="check")
        batch_op.drop_column("expired_reason")
        batch_op.drop_column("watch_window")
