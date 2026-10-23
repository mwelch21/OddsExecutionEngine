"""add deliveries: one public event going to one destination

The notifier fans each public event out into deliveries, one per event x destination
(ADR-015). `UNIQUE(event_id, destination_id)` makes fan-out idempotent, so a fan-out
interrupted by a crash can simply be redone. `locked_until` and `claim_token` let a
worker claim a delivery, commit, and only then call the push service: a claim whose
lease ran out can be taken over, and the token stops the old worker overwriting the
new one's result.

Alembic owns this schema even though only the Go notifier writes to it (ADR-013).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261018_0011"
down_revision = "20261018_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deliveries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(length=36),
            sa.ForeignKey("public_events.id"),
            nullable=False,
        ),
        sa.Column(
            "destination_id",
            sa.String(length=36),
            sa.ForeignKey("destinations.id"),
            nullable=False,
        ),
        # pending | delivered | gone | failed | expired
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(length=36), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "event_id", "destination_id", name="uq_deliveries_event_destination"
        ),
    )
    op.create_index(
        "ix_deliveries_due",
        "deliveries",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_deliveries_due", table_name="deliveries")
    op.drop_table("deliveries")
