"""Auto-Refresh live interval (#128, ADR-016)

`auto_refresh_settings.live_interval_minutes` is the cooldown of a sport with a
candidate watch on a live event. It defaults to 5, the same as the upcoming
interval, so nothing refreshes faster until the operator asks. The existing
row, if any, gets 5 through the server default. Held to 1-60 like
`interval_minutes`.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261127_0020"
down_revision = "20261127_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("auto_refresh_settings") as batch_op:
        batch_op.add_column(
            sa.Column("live_interval_minutes", sa.Integer(), nullable=False, server_default="5")
        )
        batch_op.create_check_constraint(
            "ck_auto_refresh_settings_live_interval",
            "live_interval_minutes BETWEEN 1 AND 60",
        )


def downgrade() -> None:
    with op.batch_alter_table("auto_refresh_settings") as batch_op:
        batch_op.drop_constraint("ck_auto_refresh_settings_live_interval", type_="check")
        batch_op.drop_column("live_interval_minutes")
