"""stage 5 watch intents"""

import sqlalchemy as sa
from alembic import op

revision = "20260413_0003"
down_revision = "20260412_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watch_intents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_external_id", sa.String(length=255), nullable=False),
        sa.Column("market_type", sa.String(length=32), nullable=False),
        sa.Column("selection", sa.String(length=64), nullable=False),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("target_price", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_watch_intents_event_status",
        "watch_intents",
        ["event_external_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_watch_intents_event_status", table_name="watch_intents")
    op.drop_table("watch_intents")
