# SPDX-License-Identifier: Apache-2.0
"""a CSV start's record (engine 2b spec §8.1, §7.1): the mapping, the file's header names and the skipped rows, kept
encrypted in `run_inputs` under a third role, `csv`, beside the request's envelope and claims; like the envelope, never
a claim (no pointer, at most one per request), and kept and deleted with its request"""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("run_inputs_role", "run_inputs")
    op.create_check_constraint(
        "run_inputs_role",
        "run_inputs",
        "(role = 'claim' AND pointer IS NOT NULL) OR (role IN ('envelope', 'csv') AND pointer IS NULL)",
    )
    op.create_index(
        "run_inputs_one_csv", "run_inputs", ["owner_run_id"], unique=True, postgresql_where=sa.text("role = 'csv'")
    )


def downgrade() -> None:
    op.drop_index("run_inputs_one_csv", "run_inputs")
    op.execute("DELETE FROM run_inputs WHERE role = 'csv'")
    op.drop_constraint("run_inputs_role", "run_inputs")
    op.create_check_constraint(
        "run_inputs_role",
        "run_inputs",
        "(role = 'claim' AND pointer IS NOT NULL) OR (role = 'envelope' AND pointer IS NULL)",
    )
