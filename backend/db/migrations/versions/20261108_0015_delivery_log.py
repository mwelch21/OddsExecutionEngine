"""add deliveries.ended_at and the delivery log's read indexes (#105)

`ended_at` is when a delivery reached its final status: delivered, failed, expired or
gone. The notifier stamps it on every terminal write; `delivered_at` stays as the
delivered-only time it always was. Rows already delivered take their `delivered_at`.
Rows that already failed, expired or went gone carry no record of when, so they stay
null rather than get an invented time.

The indexes serve `GET /api/v1/admin/deliveries`: newest first by status, by
destination, and the join to `public_events` filtered by type.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261108_0015"
down_revision = "20261108_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deliveries", sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE deliveries SET ended_at = delivered_at "
        "WHERE status = 'delivered' AND delivered_at IS NOT NULL"
    )
    op.create_index(
        "ix_deliveries_status_created_at", "deliveries", ["status", "created_at"]
    )
    op.create_index("ix_deliveries_destination_id", "deliveries", ["destination_id"])
    op.create_index("ix_public_events_type", "public_events", ["type"])


def downgrade() -> None:
    op.drop_index("ix_public_events_type", table_name="public_events")
    op.drop_index("ix_deliveries_destination_id", table_name="deliveries")
    op.drop_index("ix_deliveries_status_created_at", table_name="deliveries")
    op.drop_column("deliveries", "ended_at")
