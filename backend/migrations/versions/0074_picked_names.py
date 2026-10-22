# SPDX-License-Identifier: Apache-2.0
"""Editor 4f-3 (the start-form pickers design §4.1, §4.6): the names picked in a start form, kept with what they name.

- `run_inputs` gains a fourth role, `names`: a request's picked names, sealed with the tenant key beside its envelope
  and CSV record, never a claim (no pointer), at most one per request (`run_inputs_one_names`), kept and deleted with
  its request as they are. Retention, erasure and re-encryption take it as they take every `run_inputs` row.
- `schedules.names`: a schedule's picked names, sealed as its input is (purpose `schedule.names`), nullable with no
  default and null on every schedule before it. The API writes it with the input; the key admin re-encrypts it.

Online (2b-4b, D15), as 0071 widened a check: the column in a step of its own (no rewrite); the wider check added
`NOT VALID`, validated outside any transaction (it reads every row without blocking writes), then put in the old one's
place; the index built concurrently; the grants last. The downgrade drops both: names are display only, never what a
run used.

Slot 0074 is the owner's (2026-10-22, the 4f-3 spec), chained after 0073."""

import sqlalchemy as sa
from alembic import op

from migrations.online import exists, index, online, plain, step

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None

ROLES = "(role = 'claim' AND pointer IS NOT NULL) OR (role IN ('envelope', 'csv', 'names') AND pointer IS NULL)"
OLD_ROLES = "(role = 'claim' AND pointer IS NOT NULL) OR (role IN ('envelope', 'csv') AND pointer IS NULL)"
WIDER = "run_inputs_role_0074"
WIDENED = ("SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'run_inputs_role' "
           "AND pg_get_constraintdef(oid) LIKE '%names%')")  # fmt: skip


def upgrade() -> None:
    with online() as conn:
        step(conn, "0074 schedules.names", lambda: op.add_column("schedules", sa.Column("names", sa.LargeBinary)),
             done=exists("column", "names", "schedules"))  # fmt: skip
        step(conn, "0074 run_inputs_role, wider",
             f"ALTER TABLE run_inputs ADD CONSTRAINT {WIDER} CHECK ({ROLES}) NOT VALID",
             done=f"SELECT ({WIDENED}) OR ({exists('constraint', WIDER)})")  # fmt: skip
        plain(conn, "0074 run_inputs_role validated", f"ALTER TABLE run_inputs VALIDATE CONSTRAINT {WIDER}",
              done=WIDENED)  # fmt: skip
        step(conn, "0074 run_inputs_role, swapped", "ALTER TABLE run_inputs DROP CONSTRAINT run_inputs_role",
             f"ALTER TABLE run_inputs RENAME CONSTRAINT {WIDER} TO run_inputs_role", done=WIDENED)  # fmt: skip
        index(conn, "0074 run_inputs_one_names", "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS run_inputs_one_names "
              "ON run_inputs (owner_run_id) WHERE role = 'names'")  # fmt: skip
        step(conn, "0074 grants", "GRANT UPDATE (names) ON schedules TO dewpoint_api",
             "GRANT UPDATE (names) ON schedules TO dewpoint_admin")  # fmt: skip


def downgrade() -> None:
    op.drop_index("run_inputs_one_names", "run_inputs")
    op.execute("DELETE FROM run_inputs WHERE role = 'names'")
    op.drop_constraint("run_inputs_role", "run_inputs")
    op.create_check_constraint("run_inputs_role", "run_inputs", OLD_ROLES)
    op.drop_column("schedules", "names")  # its grants go with it
