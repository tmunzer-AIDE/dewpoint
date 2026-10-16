# SPDX-License-Identifier: Apache-2.0
"""Editor 4e-1 (the runs design §4.3): where a request came from, in plain ids a run's page and the runs list read.

- `run_requests.rerun_of`: the run a re-run repeats. Its audit entry names it already; the row now does.
- `run_requests.trigger_id`: the schedule a `schedule` request came from, or the webhook endpoint of a `webhook`
  request. The trigger itself stays in the request's encrypted envelope; this is its id, never a secret.

Both are nullable, with no default (a catalog change only), and null on every request before this one. No grant
changes: the roles that insert requests hold INSERT on the table, and the API holds SELECT. Online (2b-4b, D15), one
step. The downgrade drops them: they record where a request came from, never what it ran.

Slot 0073 is the owner's (the runs design §8), chained after 0072."""

from alembic import op

from migrations.online import exists, online, step

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with online() as conn:
        step(conn, "0073 run_requests columns",
             "ALTER TABLE run_requests ADD COLUMN rerun_of uuid, ADD COLUMN trigger_id uuid",
             done=exists("column", "trigger_id", "run_requests"))  # fmt: skip


def downgrade() -> None:
    op.execute("ALTER TABLE run_requests DROP COLUMN trigger_id, DROP COLUMN rerun_of")
