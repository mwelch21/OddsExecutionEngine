"""add the public outbox and wake listeners on insert

Public events (ADR-014) are the versioned CloudEvents that leave the system. They get
their own outbox, separate from the internal `workflow_events` audit trail, and are
written in the same transaction as the domain change they describe.

On Postgres, an insert trigger sends `NOTIFY public_events, '<id>'` so the notifier can
wake without polling (ADR-015). NOTIFY is transactional: listeners hear it only once
the inserting transaction commits, and never for a rolled-back row. The notifier's
30s sweep covers any notification it misses.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261018_0009"
down_revision = "20260912_0008"
branch_labels = None
depends_on = None

NOTIFY_CHANNEL = "public_events"


def upgrade() -> None:
    op.create_table(
        "public_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("type", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_public_events_undispatched",
        "public_events",
        ["created_at"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )

    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION notify_public_event() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify('{NOTIFY_CHANNEL}', NEW.id);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER public_events_notify
        AFTER INSERT ON public_events
        FOR EACH ROW EXECUTE FUNCTION notify_public_event()
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS public_events_notify ON public_events")
        op.execute("DROP FUNCTION IF EXISTS notify_public_event()")
    op.drop_index("ix_public_events_undispatched", table_name="public_events")
    op.drop_table("public_events")
