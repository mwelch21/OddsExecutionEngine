"""add destinations: where public events are delivered

One row per address on a channel (a browser's Web Push subscription today, a webhook
URL later). `address` is a dedicated column so a re-subscription can be upserted on
it; `config` holds channel-specific material such as Web Push encryption keys, which
the API never returns. Rows are soft-disabled, never deleted, so delivery history keeps
its destination.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261018_0010"
down_revision = "20261018_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "destinations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_reason", sa.String(length=32), nullable=True),
        sa.UniqueConstraint("channel", "address", name="uq_destinations_channel_address"),
    )


def downgrade() -> None:
    op.drop_table("destinations")
