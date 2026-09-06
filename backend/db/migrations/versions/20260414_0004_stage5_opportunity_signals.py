"""stage 5 opportunity signals"""

import sqlalchemy as sa
from alembic import op

revision = "20260414_0004"
down_revision = "20260413_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opportunity_signals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "watch_intent_id",
            sa.String(length=36),
            sa.ForeignKey("watch_intents.id"),
            nullable=False,
        ),
        sa.Column("event_external_id", sa.String(length=255), nullable=False),
        sa.Column("market_type", sa.String(length=32), nullable=False),
        sa.Column("selection", sa.String(length=64), nullable=False),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("matched_price", sa.Integer(), nullable=False),
        sa.Column("target_price", sa.Integer(), nullable=False),
        sa.Column("sportsbook", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_opportunity_signals_event",
        "opportunity_signals",
        ["event_external_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_opportunity_signals_event", table_name="opportunity_signals")
    op.drop_table("opportunity_signals")
