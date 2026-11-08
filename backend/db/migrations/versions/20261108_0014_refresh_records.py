"""add refresh_records, the refresh log; drop the Auto-Refresh last-outcome columns (#96)

One append-only row per refresh: manual or Auto-Refresh, sport-wide or one event,
succeeded, failed or refused. Quote ingestion is the only writer. A refresh is not an
upstream call: coalesced refreshes share one call, and a balance check is a call with
no refresh behind it.

`auto_refresh_settings.last_outcome_*` held the worker's latest outcome. The newest
`trigger = 'auto'` refresh record now answers that, so the columns go. Downgrade
brings them back empty; the outcome they held is not reconstructed.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261108_0014"
down_revision = "20261104_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("sport_key", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=True),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("events_refreshed", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("scope IN ('sport', 'event')", name="ck_refresh_records_scope"),
        sa.CheckConstraint("trigger IN ('manual', 'auto')", name="ck_refresh_records_trigger"),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'failed', 'refused')", name="ck_refresh_records_outcome"
        ),
        sa.CheckConstraint(
            "(scope = 'sport') = (event_id IS NULL)", name="ck_refresh_records_event_scope"
        ),
    )
    op.create_index("ix_refresh_records_started_at", "refresh_records", ["started_at"])

    with op.batch_alter_table("auto_refresh_settings") as batch_op:
        batch_op.drop_column("last_outcome_sport")
        batch_op.drop_column("last_outcome_status")
        batch_op.drop_column("last_outcome_at")
        batch_op.drop_column("last_outcome_events_refreshed")
        batch_op.drop_column("last_outcome_error")


def downgrade() -> None:
    with op.batch_alter_table("auto_refresh_settings") as batch_op:
        batch_op.add_column(sa.Column("last_outcome_sport", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("last_outcome_status", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("last_outcome_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_outcome_events_refreshed", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_outcome_error", sa.Text(), nullable=True))

    op.drop_index("ix_refresh_records_started_at", table_name="refresh_records")
    op.drop_table("refresh_records")
