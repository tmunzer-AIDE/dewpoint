# SPDX-License-Identifier: Apache-2.0
"""runs_workflow_last: each workflow's newest root run of each mode, for the workflows list (sub-project 4, B3; 4b
ruling 5). The list reads it in one batched LATERAL statement, one index lookup per workflow and mode, where the
statement it replaces scanned and sorted every root run of the tenant's. Slot 0047 is the owner's reservation for it.
Slot numbers name ownership, not order: it was written on main's head then (0042), and chained, when it met main, after
main's head at that merge (0044), so the chain keeps one head; main's migrations are never rewritten. Main took 0043
and 0044, which the ledger had reserved for sub-project 4 (B4b, B8): their replacement slots are the owner's to assign;
0045 and 0046 stay reserved (B7, B9)."""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0044"
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
