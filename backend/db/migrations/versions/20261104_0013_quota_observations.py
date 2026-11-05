"""add quota_observations: the credit balance seen on every upstream call (ADR-016)

One row per upstream call, manual or automatic: remaining and used credits from the
provider headers (`source = headers`), or carried forward by the local
`markets x regions` count when the headers are absent (`source = local`). The latest
row drives the quota warning, the Auto-Refresh pause and the Admin view's meter.
`remaining` and `used` stay null until anything has reported them.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261104_0013"
down_revision = "20261027_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quota_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("remaining", sa.Integer(), nullable=True),
        sa.Column("used", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("out_of_credits", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('headers', 'local')", name="ck_quota_observations_source"),
    )


def downgrade() -> None:
    op.drop_table("quota_observations")
