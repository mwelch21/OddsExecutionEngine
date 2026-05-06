"""stage 5 watch intents and opportunities"""

import sqlalchemy as sa
from alembic import op

revision = "20260418_0003"
down_revision = "20260412_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "watch_intents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_external_id", sa.String(length=255), nullable=False),
        sa.Column("market_type", sa.String(length=32), nullable=False),
        sa.Column("selection", sa.String(length=64), nullable=False),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("target_price", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "opportunities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "watch_intent_id",
            sa.String(length=36),
            sa.ForeignKey("watch_intents.id"),
            nullable=False,
        ),
        sa.Column("event_external_id", sa.String(length=255), nullable=False),
        sa.Column(
            "market_id",
            sa.String(length=36),
            sa.ForeignKey("markets.id"),
            nullable=False,
        ),
        sa.Column("sportsbook", sa.String(length=64), nullable=False),
        sa.Column("matched_price", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("opportunities")
    op.drop_table("watch_intents")
    op.drop_column("events", "starts_at")
