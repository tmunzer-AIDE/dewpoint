# SPDX-License-Identifier: Apache-2.0
"""runs_workflow_last: each workflow's newest root run of each mode, for the workflows list (sub-project 4, B3; 4b
ruling 5). The list reads it in one batched LATERAL statement, one index lookup per workflow and mode, where the
statement it replaces scanned and sorted every root run of the tenant's. Slot 0047 is the owner's reservation for it;
0043-0046 stay reserved for sub-project 4. Slot numbers name ownership, not order: chained from the head when written
(0042), so the chain keeps one head, and a later migration in a lower slot is chained after it, never rewritten."""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "runs_workflow_last",
        "runs",
        ["workflow_id", "mode", sa.text("queued_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("kind = 'run'"),
    )


def downgrade() -> None:
    op.drop_index("runs_workflow_last", table_name="runs")
