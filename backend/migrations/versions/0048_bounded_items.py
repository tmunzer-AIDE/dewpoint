# SPDX-License-Identifier: Apache-2.0
"""The leader's items bounded (the owner's D16 ruling on the 2b-4b M1 checkpoint): a run's evidence reads its history
a bounded number of pages a visit, keeping where it stopped in its row: Temporal's next-page token (`read_token`), the
run it reads (`read_run`), the children it saw initiated but not yet started (`read_pending`), its latest event's time
(`read_last_at`). A schedule incarnation that may still miss a firing (sent an unpause once, or from before 0040) is
its own item of the misses pass, read every five minutes (`misses_checked_at`) until it's verified gone
(`retired_at`: absent after it was seen, or after its schedule's deletion settled), listed across tenants, ids only, by
`incarnation_miss_candidates()`. Online (D15), in steps. Slot 0048: 0045 to 0047 are another branch's to coordinate."""

from alembic import op

from migrations.online import exists, grants, index, online, step, ungranted

revision = "0048"
down_revision = "0044"
branch_labels = None
depends_on = None

READ = ["read_token bytea", "read_run text", "read_pending jsonb", "read_last_at timestamptz"]
RETIRING = ["misses_checked_at timestamptz", "retired_at timestamptz"]
CANDIDATES = [
    """CREATE FUNCTION incarnation_miss_candidates(max_rows integer) RETURNS TABLE (tenant_id uuid, temporal_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT i.tenant_id, i.temporal_id FROM schedule_incarnations i
  WHERE i.retired_at IS NULL AND (i.backfilled OR i.unpause_sent_at IS NOT NULL OR i.landed_paused IS FALSE)
    AND (i.misses_checked_at IS NULL OR i.misses_checked_at < statement_timestamp() - interval '5 minutes')
  ORDER BY i.misses_checked_at NULLS FIRST, i.temporal_id
  LIMIT max_rows
$$""",
    "REVOKE ALL ON FUNCTION incarnation_miss_candidates(integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION incarnation_miss_candidates(integer) TO dewpoint_dispatch",
    "GRANT UPDATE (misses_checked_at, retired_at) ON schedule_incarnations TO dewpoint_dispatch",
]


def upgrade() -> None:
    with online() as conn:
        step(conn, "0048 execution_evidence read",
             f"ALTER TABLE execution_evidence {', '.join(f'ADD COLUMN {c}' for c in READ)}",
             done=exists("column", "read_token", "execution_evidence"))  # fmt: skip
        step(conn, "0048 schedule_incarnations retiring",
             f"ALTER TABLE schedule_incarnations {', '.join(f'ADD COLUMN {c}' for c in RETIRING)}",
             done=exists("column", "retired_at", "schedule_incarnations"))  # fmt: skip
        index(conn, "0048 schedule_incarnations_misses_due",
              "CREATE INDEX CONCURRENTLY IF NOT EXISTS schedule_incarnations_misses_due ON schedule_incarnations "
              "(misses_checked_at NULLS FIRST, temporal_id) WHERE retired_at IS NULL")  # fmt: skip
        step(conn, "0048 incarnation_miss_candidates", *ungranted(*CANDIDATES),
             done=exists("function", "incarnation_miss_candidates(integer)"))  # fmt: skip
        step(conn, "0048 grants", *grants(*CANDIDATES))


def downgrade() -> None:
    op.execute("REVOKE UPDATE (misses_checked_at, retired_at) ON schedule_incarnations FROM dewpoint_dispatch")
    op.execute("DROP FUNCTION incarnation_miss_candidates(integer)")
    op.execute("DROP INDEX schedule_incarnations_misses_due")
    op.execute(f"ALTER TABLE schedule_incarnations {', '.join(f'DROP COLUMN {c.split()[0]}' for c in RETIRING)}")
    op.execute(f"ALTER TABLE execution_evidence {', '.join(f'DROP COLUMN {c.split()[0]}' for c in READ)}")
