# SPDX-License-Identifier: Apache-2.0
"""The leader's items bounded (the owner's D16 ruling on the 2b-4b M1 checkpoint): a run's evidence reads its history a
bounded number of pages a visit, keeping where it stopped in its row: Temporal's next-page token (`read_token`), the run
it reads (`read_run`), the children it saw initiated but not yet started (`read_pending`), its latest event's time
(`read_last_at`). A schedule incarnation that may still miss a firing (sent an unpause once, or from before 0040) is its
own item of the misses pass, due four minutes after its last read (`misses_checked_at`), so read before its accounting
turns stale at five, until it's verified gone (`retired_at`: absent after it was seen, or after its schedule's deletion
settled), listed across tenants, ids only, by `incarnation_miss_candidates()`. Online (D15), in steps. Slot 0048, in
2b-4b's 0048 to 0065 (main's slot table, the owner, 2026-10-11). Written on 0044, and chained, when it met main, after
main's head at that merge (0070), so the chain keeps one head and main's migrations are never rewritten (slot numbers
name ownership, not order: 4b ruling 72)."""

from alembic import op

from migrations.online import exists, grants, index, online, step, ungranted

revision = "0048"
down_revision = "0070"
branch_labels = None
depends_on = None

READ = ["read_token bytea", "read_run text", "read_pending jsonb", "read_last_at timestamptz"]
RETIRING = ["misses_checked_at timestamptz", "retired_at timestamptz", "misses_tried_at timestamptz"]
# An incarnation that may still miss a firing: not yet retired, and sent an unpause once, from before 0040, or landed
# unpaused. The candidates' filter and their index's predicate, alike: one never unpaused (a disabled schedule's) is
# never read, so never in the index's way (the review's I5)
MAY_MISS = "retired_at IS NULL AND (backfilled OR unpause_sent_at IS NOT NULL OR landed_paused IS FALSE)"
# Due four minutes after its last read: read before its accounting turns stale at five (the API's `MISSES_STALE`; the
# review of checkpoint 4: due and stale at the same five minutes, every schedule showed itself incomplete each period)
MISSES_DUE = "4 minutes"
CANDIDATES = [
    f"""CREATE FUNCTION incarnation_miss_candidates(max_rows integer) RETURNS TABLE (tenant_id uuid, temporal_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT tenant_id, temporal_id FROM schedule_incarnations
  WHERE {MAY_MISS}
    AND (misses_checked_at IS NULL OR misses_checked_at < statement_timestamp() - interval '{MISSES_DUE}')
  ORDER BY misses_tried_at NULLS FIRST, temporal_id
  LIMIT max_rows
$$""",
    "REVOKE ALL ON FUNCTION incarnation_miss_candidates(integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION incarnation_miss_candidates(integer) TO dewpoint_dispatch",
    "GRANT UPDATE (misses_checked_at, retired_at, misses_tried_at) ON schedule_incarnations TO dewpoint_dispatch",
]

# Each pass's selection moves on past what it tried (the owner's review of checkpoint 4): a candidate function took the
# first items by its own order, and one that failed, or came back incomplete, kept its place for good, keeping the
# rest out. Each pass now marks what it tried (the misses read above, `misses_tried_at`; a schedule's sync, a cancel, a
# recount, here), and its candidates come least lately tried first.
TRIED = {"schedules": "sync_visited_at", "run_requests": "cancel_tried_at", "tenant_event_counters": "recount_tried_at"}
ROTATED = [
    """CREATE OR REPLACE FUNCTION schedule_candidates(max_schedules integer)
RETURNS TABLE (tenant_id uuid, schedule_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT s.tenant_id, s.id FROM schedules s
    WHERE s.generation > s.synced_generation
      AND (s.sync_error_at IS NULL OR s.sync_error_at < statement_timestamp() - interval '60 seconds')
    ORDER BY s.sync_visited_at NULLS FIRST, s.updated_at, s.id
    LIMIT max_schedules
$$""",
    """CREATE OR REPLACE FUNCTION cancel_candidates(max_rows integer)
RETURNS TABLE (tenant_id uuid, request_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT r.tenant_id, r.id FROM run_requests r JOIN runs u ON u.id = r.id
  WHERE r.status = 'started' AND r.cancel_requested_at IS NOT NULL AND r.cancel_sent_at IS NULL
    AND u.status = 'running'
  ORDER BY r.cancel_tried_at NULLS FIRST, r.cancel_requested_at, r.id
  LIMIT max_rows
$$""",
    """CREATE OR REPLACE FUNCTION recount_candidates(max_tenants integer)
RETURNS TABLE (tenant_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT c.tenant_id FROM public.tenant_event_counters c
   WHERE c.recounted_at IS NULL OR c.recounted_at <= now() - interval '10 minutes'
   ORDER BY c.recount_tried_at NULLS FIRST, c.recounted_at NULLS FIRST, c.tenant_id
   LIMIT max_tenants
$$""",
    "GRANT UPDATE (sync_visited_at) ON schedules TO dewpoint_dispatch",
    "GRANT UPDATE (recount_tried_at) ON tenant_event_counters TO dewpoint_dispatch",
]
# As 0030, 0022 and 0033 left them: the downgrade's
ORIGINAL = [
    """CREATE OR REPLACE FUNCTION schedule_candidates(max_schedules integer)
RETURNS TABLE (tenant_id uuid, schedule_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT s.tenant_id, s.id FROM schedules s
    WHERE s.generation > s.synced_generation
      AND (s.sync_error_at IS NULL OR s.sync_error_at < statement_timestamp() - interval '60 seconds')
    ORDER BY s.updated_at, s.id
    LIMIT max_schedules
$$""",
    """CREATE OR REPLACE FUNCTION cancel_candidates(max_rows integer)
RETURNS TABLE (tenant_id uuid, request_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT r.tenant_id, r.id FROM run_requests r JOIN runs u ON u.id = r.id
  WHERE r.status = 'started' AND r.cancel_requested_at IS NOT NULL AND r.cancel_sent_at IS NULL
    AND u.status = 'running'
  ORDER BY r.cancel_requested_at, r.id
  LIMIT max_rows
$$""",
    """CREATE OR REPLACE FUNCTION recount_candidates(max_tenants integer)
RETURNS TABLE (tenant_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT c.tenant_id FROM public.tenant_event_counters c
   WHERE c.recounted_at IS NULL OR c.recounted_at <= now() - interval '10 minutes'
   ORDER BY c.recounted_at NULLS FIRST, c.tenant_id
   LIMIT max_tenants
$$""",
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
              f"(misses_tried_at NULLS FIRST, temporal_id) WHERE {MAY_MISS}")  # fmt: skip
        step(conn, "0048 incarnation_miss_candidates", *ungranted(*CANDIDATES),
             done=exists("function", "incarnation_miss_candidates(integer)"))  # fmt: skip
        for table, column in TRIED.items():  # one busy table a step
            step(conn, f"0048 {table} {column}", f"ALTER TABLE {table} ADD COLUMN {column} timestamptz",
                 done=exists("column", column, table))  # fmt: skip
        index(conn, "0048 schedules_unsynced_visited",
              "CREATE INDEX CONCURRENTLY IF NOT EXISTS schedules_unsynced_visited ON schedules "
              "(sync_visited_at NULLS FIRST, updated_at, id) WHERE generation > synced_generation")  # fmt: skip
        step(conn, "0048 candidates rotated", *ungranted(*ROTATED))
        step(conn, "0048 grants", *grants(*CANDIDATES), *grants(*ROTATED))


def downgrade() -> None:
    for statement in ORIGINAL:
        op.execute(statement)
    op.execute("REVOKE UPDATE (recount_tried_at) ON tenant_event_counters FROM dewpoint_dispatch")
    op.execute("REVOKE UPDATE (sync_visited_at) ON schedules FROM dewpoint_dispatch")
    op.execute("DROP INDEX schedules_unsynced_visited")
    for table, column in TRIED.items():
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    op.execute("REVOKE UPDATE (misses_checked_at, retired_at, misses_tried_at) ON schedule_incarnations "
               "FROM dewpoint_dispatch")  # fmt: skip
    op.execute("DROP FUNCTION incarnation_miss_candidates(integer)")
    op.execute("DROP INDEX schedule_incarnations_misses_due")
    op.execute(f"ALTER TABLE schedule_incarnations {', '.join(f'DROP COLUMN {c.split()[0]}' for c in RETIRING)}")
    op.execute(f"ALTER TABLE execution_evidence {', '.join(f'DROP COLUMN {c.split()[0]}' for c in READ)}")
