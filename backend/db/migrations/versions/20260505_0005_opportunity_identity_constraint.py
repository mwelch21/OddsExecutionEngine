"""stage 6 opportunity identity constraint"""

from alembic import op

revision = "20260505_0005"
down_revision = "20260420_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        DELETE FROM opportunities
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY watch_intent_id, market_id, sportsbook
                        ORDER BY created_at ASC, id ASC
                    ) AS row_num
                FROM opportunities
            ) ranked
            WHERE row_num > 1
        )
        """
    )

    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.create_unique_constraint(
            "uq_opportunities_identity",
            ["watch_intent_id", "market_id", "sportsbook"],
        )


def downgrade() -> None:
    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.drop_constraint("uq_opportunities_identity", type_="unique")
