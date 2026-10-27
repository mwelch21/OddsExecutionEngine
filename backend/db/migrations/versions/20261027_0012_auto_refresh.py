"""add Auto-Refresh settings and per-sport last refresh time (ADR-016)

`auto_refresh_settings` is a single row (`id = 1`) holding the operator's switch,
interval and quota floor, plus the worker's last refresh outcome. It is not seeded:
an absent row reads as the defaults (off, 5 minutes), so a truncated database still
behaves.

`sport_refreshes` records when each provider sport key was last pulled sport-wide,
by hand or by the worker. The cooldown is derived from it; there is no stored due
time.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0012"
down_revision = "20261018_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_refresh_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("quota_floor", sa.Integer(), nullable=True),
        sa.Column("last_outcome_sport", sa.String(length=64), nullable=True),
        sa.Column("last_outcome_status", sa.String(length=16), nullable=True),
        sa.Column("last_outcome_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outcome_events_refreshed", sa.Integer(), nullable=True),
        sa.Column("last_outcome_error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="ck_auto_refresh_settings_single_row"),
        sa.CheckConstraint(
            "interval_minutes BETWEEN 1 AND 60",
            name="ck_auto_refresh_settings_interval",
        ),
    )
    op.create_table(
        "sport_refreshes",
        sa.Column("sport_key", sa.String(length=64), primary_key=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sport_refreshes")
    op.drop_table("auto_refresh_settings")
