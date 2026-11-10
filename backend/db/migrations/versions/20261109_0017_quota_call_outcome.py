"""record how each upstream call ended on quota_observations (#121)

`call_outcome` says how the call ended: `answered`, `out_of_credits`,
`network_error` (no response at all), `server_error` (5xx), `auth_failure`
(401/403), `rate_limited` (429 that is not out of credits), `invalid_response`
(a 2xx body that is not usable) or `client_error` (any other 4xx). The odds
provider's component status reads it off the newest upstream call, balance
checks included.

Rows recorded before this revision keep a null outcome: how those calls ended was
never kept, so nothing is backfilled, and a null outcome reads as Unknown.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261109_0017"
down_revision = "20261108_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("quota_observations") as batch_op:
        batch_op.add_column(sa.Column("call_outcome", sa.String(length=16), nullable=True))
        batch_op.create_check_constraint(
            "ck_quota_observations_call_outcome",
            "call_outcome IS NULL OR call_outcome IN ('answered', 'out_of_credits',"
            " 'network_error', 'server_error', 'auth_failure', 'rate_limited',"
            " 'invalid_response', 'client_error')",
        )


def downgrade() -> None:
    with op.batch_alter_table("quota_observations") as batch_op:
        batch_op.drop_constraint("ck_quota_observations_call_outcome", type_="check")
        batch_op.drop_column("call_outcome")
