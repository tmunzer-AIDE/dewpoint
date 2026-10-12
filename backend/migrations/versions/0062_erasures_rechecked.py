# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4 recovery, task 14: the lifelong check covers incomplete erasures (design revision 5 §6, revision 7 §3).

- `erasures_rechecked()`, in place of 0040's `erasures_completed()` for the reconciliation: every completed erasure,
  and every one past step 60 with anything unresolved (`erasure_unresolved`, 0061), stopped or not: held at 90, at 70
  or 80. It decides from the rows, never from the display counter, so a counter that drifts drops nothing. An erasure
  at 60 or before is its stages' own (a reopen there would skip the fence and the stages before it).

One transaction, Alembic's own, each lock wait bounded (5 s): one function, no table changed. It keeps no row, so its
downgrade refuses nothing."""

from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
FUNCTIONS = [
    """CREATE FUNCTION erasures_rechecked() RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT e.tenant_id FROM tenant_erasures e
   WHERE e.completed_at IS NOT NULL OR (e.step > 60 AND erasure_unresolved(e.tenant_id) > 0)
   ORDER BY e.tenant_id
$$""",
    "REVOKE ALL ON FUNCTION erasures_rechecked() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION erasures_rechecked() TO dewpoint_retention",
]


def upgrade() -> None:
    for statement in (LOCK_TIMEOUT, *FUNCTIONS):
        op.execute(statement)


def downgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute("DROP FUNCTION erasures_rechecked()")
