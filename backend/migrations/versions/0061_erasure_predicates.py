# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4 recovery, task 12: step 60 settles without claiming verification; no bound while anything is unresolved
(design revision 4 §3, revision 5 §3 and §7, revision 6 §7).

- An item's state gains `absent`: an id alone that every describe answered NOT_FOUND, never shown. Never `verified`.
- `erasure_unresolved(tenant)`: what's unresolved for the tenant, counted from the rows themselves (never the display
  counter): its known executions `absent`, `run_not_found` or `legacy`; its `absent` items; its `unresolved_sends`, in
  any state. Read by step 60's advance (the bound only at 0), step 90's first hold, the lifelong recheck and the API.
- `erasure_proven(tenant)`: completed, with no qualification and nothing unresolved: what a proof-dependent gate reads,
  never `completed_at` alone.

One transaction, Alembic's own, each lock wait bounded (5 s). Its downgrade refuses while an item is `absent` (before
0061 it has no place), its lock taken before it checks."""

from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
STATES = ["ALTER TABLE tenant_erasure_items DROP CONSTRAINT tenant_erasure_items_state, ADD CONSTRAINT "
          "tenant_erasure_items_state CHECK (state IN ('found', 'requested', 'verified', 'absent'))"]  # fmt: skip
STATES_0040 = ["ALTER TABLE tenant_erasure_items DROP CONSTRAINT tenant_erasure_items_state, ADD CONSTRAINT "
               "tenant_erasure_items_state CHECK (state IN ('found', 'requested', 'verified'))"]  # fmt: skip
FUNCTIONS = [
    "CREATE INDEX unresolved_sends_tenant ON unresolved_sends (tenant_id)",
    """CREATE FUNCTION erasure_unresolved(tenant uuid) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT (SELECT count(*) FROM tenant_erasure_known k
           WHERE k.tenant_id = $1 AND k.kind = 'execution' AND k.provenance IN ('absent', 'run_not_found', 'legacy'))
       + (SELECT count(*) FROM tenant_erasure_items i WHERE i.tenant_id = $1 AND i.state = 'absent')
       + (SELECT count(*) FROM unresolved_sends b WHERE b.tenant_id = $1)
$$""",
    """CREATE FUNCTION erasure_proven(tenant uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT coalesce((SELECT e.completed_at IS NOT NULL AND e.qualification IS NULL FROM tenant_erasures e
                    WHERE e.tenant_id = $1), false)
         AND erasure_unresolved($1) = 0
$$""",
    "REVOKE ALL ON FUNCTION erasure_unresolved(uuid), erasure_proven(uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION erasure_unresolved(uuid), erasure_proven(uuid) TO dewpoint_retention, dewpoint_api",
]
LOCKED = "LOCK TABLE tenant_erasure_items IN ACCESS EXCLUSIVE MODE"
REFUSE_DOWNGRADE = """DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM tenant_erasure_items WHERE state = 'absent') THEN
    RAISE EXCEPTION '0061 refused: an item is absent (an id never shown: before 0061 it would read as verified)';
  END IF;
END $$"""


def upgrade() -> None:
    for statement in (LOCK_TIMEOUT, *STATES, *FUNCTIONS):
        op.execute(statement)


def downgrade() -> None:
    for statement in (LOCK_TIMEOUT, LOCKED, REFUSE_DOWNGRADE, *STATES_0040):
        op.execute(statement)
    op.execute("DROP FUNCTION erasure_proven(uuid)")
    op.execute("DROP FUNCTION erasure_unresolved(uuid)")
    op.execute("DROP INDEX unresolved_sends_tenant")
