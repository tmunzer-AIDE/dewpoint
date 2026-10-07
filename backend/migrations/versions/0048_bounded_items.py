# SPDX-License-Identifier: Apache-2.0
"""The leader's items bounded (the owner's D16 ruling on the 2b-4b M1 checkpoint): a run's evidence reads its history
a bounded number of pages a visit, keeping where it stopped in its row: Temporal's next-page token (`read_token`), the
run it reads (`read_run`), the children it saw initiated but not yet started (`read_pending`), its latest event's time
(`read_last_at`). Online (D15), in a step. Slot 0048: 0045 to 0047 are another branch's to coordinate."""

from alembic import op

from migrations.online import exists, online, step

revision = "0048"
down_revision = "0044"
branch_labels = None
depends_on = None

READ = ["read_token bytea", "read_run text", "read_pending jsonb", "read_last_at timestamptz"]


def upgrade() -> None:
    with online() as conn:
        step(conn, "0048 execution_evidence read",
             f"ALTER TABLE execution_evidence {', '.join(f'ADD COLUMN {c}' for c in READ)}",
             done=exists("column", "read_token", "execution_evidence"))  # fmt: skip


def downgrade() -> None:
    op.execute(f"ALTER TABLE execution_evidence {', '.join(f'DROP COLUMN {c.split()[0]}' for c in READ)}")
