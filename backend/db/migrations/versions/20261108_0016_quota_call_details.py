"""widen quota_observations with what each call was and spent; link refreshes to calls (#104)

Each upstream call now records its kind (`sport | event | balance_check`), the sport
and event it named, and the credits it spent (`x-requests-last`, or the local
`markets x regions` count when that header is absent). Credit burn is summed from
these rows, since upstream calls are what get billed.

`refresh_records.quota_observation_id` points at the call a refresh used. Refreshes
coalesced into one call share it; a refresh that failed before any call has none.
Cost is read through the link, never stored twice.

Rows recorded before this revision keep null kind, sport, event and spend: what
those calls were was never kept, so nothing is backfilled.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261108_0016"
down_revision = "20261108_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("quota_observations") as batch_op:
        batch_op.add_column(sa.Column("call_kind", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("sport_key", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("event_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("credits_spent", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "ck_quota_observations_call_kind",
            "call_kind IS NULL OR call_kind IN ('sport', 'event', 'balance_check')",
        )
    op.create_index("ix_quota_observations_observed_at", "quota_observations", ["observed_at"])

    with op.batch_alter_table("refresh_records") as batch_op:
        batch_op.add_column(sa.Column("quota_observation_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_refresh_records_quota_observation_id",
            "quota_observations",
            ["quota_observation_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("refresh_records") as batch_op:
        batch_op.drop_constraint("fk_refresh_records_quota_observation_id", type_="foreignkey")
        batch_op.drop_column("quota_observation_id")

    op.drop_index("ix_quota_observations_observed_at", table_name="quota_observations")
    with op.batch_alter_table("quota_observations") as batch_op:
        batch_op.drop_constraint("ck_quota_observations_call_kind", type_="check")
        batch_op.drop_column("credits_spent")
        batch_op.drop_column("event_id")
        batch_op.drop_column("sport_key")
        batch_op.drop_column("call_kind")
