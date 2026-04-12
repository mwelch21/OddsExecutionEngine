"""stage 2 enhanced initial schema"""

# ruff: noqa: I001

from alembic import op
import sqlalchemy as sa


revision = "20260411_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("external_id", sa.String(length=255), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "order_intents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_external_id", sa.String(length=255), nullable=False),
        sa.Column("market_type", sa.String(length=32), nullable=False),
        sa.Column("selection", sa.String(length=64), nullable=False),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("target_price", sa.Integer(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "markets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_id", sa.String(length=36), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("market_type", sa.String(length=32), nullable=False),
        sa.Column("selection", sa.String(length=64), nullable=False),
        sa.Column("line", sa.Float(), nullable=True),
        sa.Column("line_key", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "event_id",
            "market_type",
            "selection",
            "line_key",
            name="uq_markets_identity",
        ),
    )
    op.create_table(
        "execution_recommendations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "order_intent_id",
            sa.String(length=36),
            sa.ForeignKey("order_intents.id"),
            nullable=False,
        ),
        sa.Column("fillable", sa.Boolean(), nullable=False),
        sa.Column("matched_quote_count", sa.Integer(), nullable=False),
        sa.Column("best_quote", sa.JSON(), nullable=True),
        sa.Column("nearest_miss", sa.JSON(), nullable=True),
        sa.Column("ranked_quotes", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "market_quotes_history",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("market_id", sa.String(length=36), sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("sportsbook", sa.String(length=64), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column(
            "quoted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "market_quotes_latest",
        sa.Column("market_id", sa.String(length=36), sa.ForeignKey("markets.id"), primary_key=True),
        sa.Column("sportsbook", sa.String(length=64), primary_key=True),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column(
            "quoted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("market_quotes_latest")
    op.drop_table("market_quotes_history")
    op.drop_table("execution_recommendations")
    op.drop_table("markets")
    op.drop_table("order_intents")
    op.drop_table("events")
