"""stage 6 event metadata and participants"""

import sqlalchemy as sa
from alembic import op

revision = "20260420_0004"
down_revision = "20260418_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    existing_columns = {c["name"] for c in inspector.get_columns("events")}

    if "sport" not in existing_columns:
        op.add_column(
            "events",
            sa.Column("sport", sa.String(length=64), nullable=True),
        )
    if "league" not in existing_columns:
        op.add_column(
            "events",
            sa.Column("league", sa.String(length=64), nullable=True),
        )
    if "status" not in existing_columns:
        op.add_column(
            "events",
            sa.Column("status", sa.String(length=16), nullable=False, server_default="upcoming"),
        )
    if "provider" not in existing_columns:
        op.add_column(
            "events",
            sa.Column("provider", sa.String(length=32), nullable=True),
        )

    # Drop legacy columns from earlier migration attempt
    if "home_team" in existing_columns:
        op.drop_column("events", "home_team")
    if "away_team" in existing_columns:
        op.drop_column("events", "away_team")

    existing_tables = set(inspector.get_table_names())
    if "event_participants" not in existing_tables:
        op.create_table(
            "event_participants",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "event_id",
                sa.String(length=36),
                sa.ForeignKey("events.id"),
                nullable=False,
            ),
            sa.Column("participant_name", sa.String(length=128), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("side", sa.String(length=16), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_table("event_participants")
    op.drop_column("events", "provider")
    op.drop_column("events", "status")
    op.drop_column("events", "league")
    op.drop_column("events", "sport")
