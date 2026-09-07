"""watch intent ttl

Adds the nullable `expires_at` TTL column to watch_intents. Existing rows get NULL,
which means "no TTL" and preserves their current behaviour.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260510_0006"
down_revision = "20260505_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "watch_intents",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_watch_intents_status_expires_at",
        "watch_intents",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_watch_intents_status_expires_at", table_name="watch_intents")
    op.drop_column("watch_intents", "expires_at")
