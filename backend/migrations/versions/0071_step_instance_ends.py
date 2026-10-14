# SPDX-License-Identifier: Apache-2.0
"""B4b (editor 4d-1a; the simulation design §3): every step instance's end is recorded.

- `run_steps.status` gains `skipped` (a branch not taken) and `not_started` (an instance discarded before it began: a
  scope's failure, a stop or fail step, a cancel, the deadline; or a retry that never began).
- `run_steps.effect_preview`: what a control step did besides its output, protected like `output_preview`: the port an
  `if` or a `switch` took (`{"port": …}`), the variables a `set_variables` assigned (`{"assignments": …}`).

Online (2b-4b, D15): the column is added in a step of its own (no rewrite); the wider check is added `NOT VALID` in
another, validated outside any transaction (it reads every row without blocking writes), then put in the old one's
place. The roles' table grants on `run_steps` cover the new column. Its downgrade refuses while a row records either
new status or an effect: dropping them would lose what ABI-9 runs recorded (stop the ABI-9 workers first)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.online import exists, online, plain, step

revision = "0071"
down_revision = "0065"
branch_labels = None
depends_on = None

STATUSES = "('running', 'succeeded', 'failed', 'cancelled', 'skipped', 'not_started')"
WIDER = "run_steps_status_0071"
WIDENED = ("SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'run_steps_status' "
           "AND pg_get_constraintdef(oid) LIKE '%not_started%')")  # fmt: skip
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
REFUSE_DOWNGRADE = """DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM run_steps WHERE status IN ('skipped', 'not_started') OR effect_preview IS NOT NULL) THEN
    RAISE EXCEPTION '0071 refused: a step row records skipped, not_started or an effect';
  END IF;
END $$"""


def upgrade() -> None:
    with online() as conn:
        step(conn, "0071 run_steps.effect_preview",
             lambda: op.add_column("run_steps", sa.Column("effect_preview", JSONB())),
             done=exists("column", "effect_preview", "run_steps"))  # fmt: skip
        step(conn, "0071 run_steps_status, wider",
             f"ALTER TABLE run_steps ADD CONSTRAINT {WIDER} CHECK (status IN {STATUSES}) NOT VALID",
             done=f"SELECT ({WIDENED}) OR ({exists('constraint', WIDER)})")  # fmt: skip
        plain(conn, "0071 run_steps_status validated", f"ALTER TABLE run_steps VALIDATE CONSTRAINT {WIDER}",
              done=WIDENED)  # fmt: skip
        step(conn, "0071 run_steps_status, swapped", "ALTER TABLE run_steps DROP CONSTRAINT run_steps_status",
             f"ALTER TABLE run_steps RENAME CONSTRAINT {WIDER} TO run_steps_status", done=WIDENED)  # fmt: skip


def downgrade() -> None:
    for statement in (LOCK_TIMEOUT, "LOCK TABLE run_steps IN SHARE MODE", REFUSE_DOWNGRADE):
        op.execute(statement)
    op.execute("ALTER TABLE run_steps DROP CONSTRAINT run_steps_status")
    op.execute(
        "ALTER TABLE run_steps ADD CONSTRAINT run_steps_status "
        "CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled'))"
    )
    op.drop_column("run_steps", "effect_preview")
