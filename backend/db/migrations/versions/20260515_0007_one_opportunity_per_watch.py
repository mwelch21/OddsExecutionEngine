"""one opportunity per watch, carrying every matching book

Reshapes `opportunities` from one row per (watch_intent_id, market_id, sportsbook)
to one row per watch:

- `sportsbook` / `matched_price` become `best_sportsbook` / `best_price`
- `matching_quotes` (JSON) holds every book that was fillable at detection time
- `uq_opportunities_identity` gives way to `unique(watch_intent_id)`, which is the
  real invariant now that a watch is terminal once it fires

Existing rows are DELETED, not backfilled. This destruction is intentional: the
per-book rows are test data, and grouping logic that runs exactly once against data
nobody will miss is more likely to produce plausible-looking wrong history than to
earn its keep. Seed data regenerates with `odds-db-seed-demo`.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260515_0007"
down_revision = "20260510_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Emptied first so the NOT NULL columns below can be added without a default.
    op.execute(sa.text("DELETE FROM opportunities"))

    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.drop_constraint("uq_opportunities_identity", type_="unique")
        batch_op.drop_column("sportsbook")
        batch_op.drop_column("matched_price")
        batch_op.add_column(
            sa.Column("best_sportsbook", sa.String(length=64), nullable=False)
        )
        batch_op.add_column(sa.Column("best_price", sa.Integer(), nullable=False))
        batch_op.add_column(sa.Column("matching_quotes", sa.JSON(), nullable=False))
        batch_op.create_unique_constraint(
            "uq_opportunities_watch_intent", ["watch_intent_id"]
        )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM opportunities"))

    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.drop_constraint("uq_opportunities_watch_intent", type_="unique")
        batch_op.drop_column("matching_quotes")
        batch_op.drop_column("best_price")
        batch_op.drop_column("best_sportsbook")
        batch_op.add_column(
            sa.Column("sportsbook", sa.String(length=64), nullable=False)
        )
        batch_op.add_column(sa.Column("matched_price", sa.Integer(), nullable=False))
        batch_op.create_unique_constraint(
            "uq_opportunities_identity",
            ["watch_intent_id", "market_id", "sportsbook"],
        )
