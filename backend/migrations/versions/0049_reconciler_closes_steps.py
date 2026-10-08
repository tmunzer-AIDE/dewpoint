# SPDX-License-Identifier: Apache-2.0
"""A run's steps never left `running` once their outcome can't come (the owner's rulings on the 2b-4b M2 checkpoint):
an unexpected bug failed the run's execution, or a batch of it, which never projected them.

- The reconciler closes a run's steps still `running` when it records the run's end, in that same transaction, so a
  projection landing later sees the run ended and lands closed: grants, column by column as 0048's, of what picks the
  rows and what closes them.
- A batch a bug failed is closed by its parent while the run still runs, and its closing is kept on the run's row
  (`unconfirmed_batches`, a list of `{scope, loop, start, end}`), which a projection reads under the row's lock: a
  projection of the batch landing later lands closed too. A nullable column: no rewrite.

Online (D15), in steps. Slot 0049: 0045 to 0047 are another branch's to coordinate."""

from alembic import op

from migrations.online import exists, online, step

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

CLOSING = (
    "GRANT SELECT (run_id, status, iteration_key), UPDATE (status, error_code, error_message, ended_at) ON run_steps "
    "TO dewpoint_dispatch"
)


def upgrade() -> None:
    with online() as conn:
        step(conn, "0049 runs unconfirmed_batches", "ALTER TABLE runs ADD COLUMN unconfirmed_batches jsonb",
             done=exists("column", "unconfirmed_batches", "runs"))  # fmt: skip
        step(conn, "0049 grants", CLOSING)


def downgrade() -> None:
    op.execute(
        "REVOKE SELECT (run_id, status, iteration_key), UPDATE (status, error_code, error_message, ended_at) "
        "ON run_steps FROM dewpoint_dispatch"
    )
    op.execute("ALTER TABLE runs DROP COLUMN unconfirmed_batches")
