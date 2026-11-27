"""Auto-Refresh sport focus (#132, ADR-016)

`auto_refresh_settings.sport_focus` is the operator's pick of catalog sport
keys (the keys `GET /api/v1/sports` returns, such as `basketball_nba`). A
non-empty focus narrows Auto-Refresh to those sports and is the events view's
default filter. Empty means no focus. The existing row, if any, gets empty
through the server default, so behavior does not change on upgrade.

On Postgres the column is `text[]`: the element type is enforced, and an empty
array reads back as an empty set. SQLite (local smoke only) has no array type,
so it stores the same list as JSON. The application stores keys sorted and
de-duplicated; catalog membership is checked by the application, because the
catalog comes from the provider adapter, not from a table.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261127_0021"
down_revision = "20261127_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    column: sa.Column[object]
    if op.get_bind().dialect.name == "postgresql":
        column = sa.Column(
            "sport_focus",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        )
    else:
        column = sa.Column(
            "sport_focus", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        )
    with op.batch_alter_table("auto_refresh_settings") as batch_op:
        batch_op.add_column(column)


def downgrade() -> None:
    with op.batch_alter_table("auto_refresh_settings") as batch_op:
        batch_op.drop_column("sport_focus")
