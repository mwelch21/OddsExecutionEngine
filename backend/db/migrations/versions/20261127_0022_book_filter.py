"""Allowed-books filter (#136)

`book_filter_settings.sportsbooks` is the operator's pick of sportsbook names
(the exact `sportsbook` strings on stored quotes). Quotes from other books are
still ingested and stored; reads and evaluation skip them. Empty means all
books, so behavior does not change on upgrade: no row reads as all books.

Its own table, not a column on `auto_refresh_settings`: the filter is not an
Auto-Refresh setting, and it gains a user key once auth lands (#14). One row for
now, held to `id = 1`.

On Postgres the column is `text[]`; SQLite (local smoke only) stores the list as
JSON. The application stores names sorted and de-duplicated.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261127_0022"
down_revision = "20261127_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sportsbooks: sa.Column[object]
    if op.get_bind().dialect.name == "postgresql":
        sportsbooks = sa.Column(
            "sportsbooks",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        )
    else:
        sportsbooks = sa.Column(
            "sportsbooks", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        )
    op.create_table(
        "book_filter_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sportsbooks,
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="ck_book_filter_settings_single_row"),
    )


def downgrade() -> None:
    op.drop_table("book_filter_settings")
