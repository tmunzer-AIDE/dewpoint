# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4 recovery, task 5: unresolved requests, paced; the owed slot's and the late start's recovery reasons (the
design's revisions 2 and 3; the owner's rulings 1 to 3 on it).

- Three recovery reasons (0050's `REASONS`, a check on `recovery_items` and on `operator_commands`):
  `start_over_limit`, a late sighting's owed slot reserved over its tenant's limit, live while its run is;
  `late_start`, a root execution of an ended request terminated on the exact match; and `late_start_unmatched`, one
  whose first run carries another id, never terminated (the owner's ruling, design revision 2, section D). Both late
  starts are an operator's: no pass clears them (`work_settled_clear`).
- A late start's durable record, on its blocker (`unresolved_sends.late_start`, `matched` or `unmatched`, and
  `late_start_at`): written once, before any termination, and never refused by the erasure's insert fence, which
  refuses the recovery item from stage 60 (the owner's second gate-B review). Its audit entry is written with it.
- Pacing (`reconcile_candidates`): a spent request left unresolved (its `start_unresolved` noted) is described again
  `reconcile.next_look` after its last look: 30 s after it was noted, then twice the last gap, up to an hour. A look
  `previous` after the one before was made 2 x previous - 30 s after the noting, so the next is due `least(last look -
  noted + recheck, 1 hour)` after the last: read from the rows, no column of its own. Monitoring only: it resolves
  nothing.

One transaction, Alembic's own, each lock wait bounded (5 s): two functions replaced and two checks replaced, on the
small `recovery_items` and `operator_commands`, and two nullable columns on the blocker store (no rewrite). Its
downgrade refuses while any new reason, or a blocker's late-start record, is kept."""

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
REASONS_0050 = (
    "start_after_end",
    "start_history_missing",
    "start_unresolved",
    "run_history_missing",
    "slot_history_missing",
    "subrun_history_missing",
)
REASONS = (*REASONS_0050, "start_over_limit", "late_start", "late_start_unmatched")
CHECKED = "  WHERE (q.checked_at IS NULL OR q.checked_at < statement_timestamp() - recheck)\n"
PACED = (
    "    AND NOT (c.kind = 'starting' AND (q.sends >= 10 OR q.attempts >= 10) AND q.checked_at IS NOT NULL\n"
    "             AND EXISTS (SELECT 1 FROM recovery_items i WHERE i.tenant_id = q.tenant_id AND i.item_id = q.id\n"
    "                           AND i.reason = 'start_unresolved'\n"
    "                           AND q.checked_at >= statement_timestamp()\n"
    "                                               - least(q.checked_at - i.since + recheck, interval '1 hour')))\n"
)
LIVE_0050 = """          WHEN 'slot_history_missing' THEN EXISTS (SELECT 1 FROM run_slots t WHERE t.run_id = i.item_id
                                                     AND t.tenant_id = i.tenant_id)
"""
LIVE = (
    LIVE_0050
    + """          WHEN 'start_over_limit' THEN EXISTS (SELECT 1 FROM runs u WHERE u.id = i.item_id
                                                 AND u.tenant_id = i.tenant_id AND u.status = 'running')
          WHEN 'late_start' THEN true
          WHEN 'late_start_unmatched' THEN true
"""
)
RECONCILE_0050 = """CREATE OR REPLACE FUNCTION reconcile_candidates(grace interval, recheck interval, max_rows integer)
RETURNS TABLE (tenant_id uuid, request_id uuid, kind text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT c.tenant_id, c.request_id, c.kind FROM (
    SELECT r.tenant_id, r.id AS request_id, 'starting'::text AS kind, r.starting_at AS since
    FROM run_requests r
    WHERE r.status = 'starting' AND r.starting_at < statement_timestamp() - grace
    UNION ALL
    SELECT r.tenant_id, r.id, 'open', u.queued_at
    FROM run_requests r JOIN runs u ON u.id = r.id
    WHERE r.status = 'started' AND u.status = 'running'
    UNION ALL
    SELECT s.tenant_id, s.run_id, 'slot', s.reserved_at
    FROM run_slots s JOIN runs u ON u.id = s.run_id JOIN run_requests r ON r.id = s.run_id
    WHERE r.status <> 'starting' AND u.status <> 'running'
  ) c JOIN run_requests q ON q.id = c.request_id
  WHERE (q.checked_at IS NULL OR q.checked_at < statement_timestamp() - recheck)
    AND NOT EXISTS (SELECT 1 FROM work_failures f WHERE f.tenant_id = c.tenant_id AND f.item_id = c.request_id AND f.kind = 'reconcile_' || c.kind AND (f.held_at IS NOT NULL OR f.due_at > now()))
  ORDER BY q.checked_at NULLS FIRST, c.since, c.request_id
  LIMIT max_rows
$$"""
SETTLED_0050 = """CREATE OR REPLACE FUNCTION work_settled_clear(max_rows integer) RETURNS integer
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  WITH failures AS (
    DELETE FROM work_failures f WHERE (f.tenant_id, f.item_id, f.kind) IN (
      SELECT w.tenant_id, w.item_id, w.kind FROM work_failures w WHERE NOT (CASE w.kind
          WHEN 'dispatch' THEN EXISTS (SELECT 1 FROM run_requests q WHERE q.id = w.item_id AND q.tenant_id = w.tenant_id
                                         AND q.status = 'queued')
          WHEN 'reconcile_starting' THEN EXISTS (SELECT 1 FROM run_requests q WHERE q.id = w.item_id
                                                   AND q.tenant_id = w.tenant_id AND q.status = 'starting')
          WHEN 'reconcile_open' THEN EXISTS (SELECT 1 FROM run_requests q JOIN runs u ON u.id = q.id
                                               WHERE q.id = w.item_id AND q.tenant_id = w.tenant_id
                                                 AND q.status = 'started' AND u.status = 'running')
          WHEN 'reconcile_slot' THEN EXISTS (SELECT 1 FROM run_slots t WHERE t.run_id = w.item_id
                                               AND t.tenant_id = w.tenant_id)
          WHEN 'cancel' THEN EXISTS (SELECT 1 FROM run_requests q JOIN runs u ON u.id = q.id
                                       WHERE q.id = w.item_id AND q.tenant_id = w.tenant_id AND q.status = 'started'
                                         AND q.cancel_requested_at IS NOT NULL AND q.cancel_sent_at IS NULL
                                         AND u.status = 'running')
          WHEN 'match' THEN EXISTS (SELECT 1 FROM inbound_events e WHERE e.id = w.item_id AND e.tenant_id = w.tenant_id
                                      AND e.status = 'pending')
          WHEN 'subrun' THEN EXISTS (SELECT 1 FROM runs u WHERE u.id = w.item_id AND u.tenant_id = w.tenant_id
                                       AND u.status = 'running')
          ELSE true END) LIMIT max_rows)
    RETURNING 1
  ), reasons AS (
    DELETE FROM recovery_items r WHERE (r.tenant_id, r.item_id, r.reason) IN (
      SELECT i.tenant_id, i.item_id, i.reason FROM recovery_items i WHERE NOT (CASE i.reason
          WHEN 'run_history_missing' THEN EXISTS (SELECT 1 FROM runs u WHERE u.id = i.item_id
                                                    AND u.tenant_id = i.tenant_id AND u.status = 'running')
          WHEN 'subrun_history_missing' THEN EXISTS (SELECT 1 FROM runs u WHERE u.id = i.item_id
                                                       AND u.tenant_id = i.tenant_id AND u.status = 'running')
          WHEN 'slot_history_missing' THEN EXISTS (SELECT 1 FROM run_slots t WHERE t.run_id = i.item_id
                                                     AND t.tenant_id = i.tenant_id)
          ELSE EXISTS (SELECT 1 FROM run_requests q WHERE q.id = i.item_id AND q.tenant_id = i.tenant_id
                         AND q.status = 'starting') END) LIMIT max_rows)
    RETURNING 1
  )
  SELECT ((SELECT count(*) FROM failures) + (SELECT count(*) FROM reasons))::integer
$$"""


def _once(text: str, anchor: str, replacement: str) -> str:
    if text.count(anchor) != 1:
        raise ValueError(anchor)
    return text.replace(anchor, replacement)


RECONCILE = _once(RECONCILE_0050, CHECKED, CHECKED + PACED)
SETTLED = _once(SETTLED_0050, LIVE_0050, LIVE)


def _reasons(values: tuple[str, ...]) -> list[str]:
    within = ", ".join(f"'{v}'" for v in values)
    return [f"ALTER TABLE {table} DROP CONSTRAINT {table}_reason, "
            f"ADD CONSTRAINT {table}_reason CHECK (reason IN ({within}))"
            for table in ("recovery_items", "operator_commands")]  # fmt: skip


LATE_START = [
    "ALTER TABLE unresolved_sends ADD COLUMN late_start text NULL "
    "CONSTRAINT unresolved_sends_late_start CHECK (late_start IN ('matched', 'unmatched')), "
    "ADD COLUMN late_start_at timestamptz NULL, "
    "ADD CONSTRAINT unresolved_sends_late_start_at CHECK ((late_start IS NULL) = (late_start_at IS NULL))",
]
REFUSE_DOWNGRADE = """DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM recovery_items WHERE reason IN ('start_over_limit', 'late_start', 'late_start_unmatched'))
     OR EXISTS (SELECT 1 FROM operator_commands
                 WHERE reason IN ('start_over_limit', 'late_start', 'late_start_unmatched'))
     OR EXISTS (SELECT 1 FROM unresolved_sends WHERE late_start IS NOT NULL) THEN
    RAISE EXCEPTION '0055 refused: a late start or an over-limit slot is recorded: an operator''s, never dropped';
  END IF;
END $$"""


# Taken before the refusal checks, so a record committed while the downgrade waits is seen, never dropped (the owner's
# third gate-B review), in the order a sighting writes them (the blocker's record, then its item)
LOCKED = "LOCK TABLE unresolved_sends, recovery_items, operator_commands IN ACCESS EXCLUSIVE MODE"


def upgrade() -> None:
    for statement in (LOCK_TIMEOUT, *_reasons(REASONS), *LATE_START, RECONCILE, SETTLED):
        op.execute(statement)


def downgrade() -> None:
    for statement in (LOCK_TIMEOUT, LOCKED, REFUSE_DOWNGRADE, *_reasons(REASONS_0050), RECONCILE_0050, SETTLED_0050):
        op.execute(statement)
    op.execute("ALTER TABLE unresolved_sends DROP COLUMN late_start_at, DROP COLUMN late_start")
