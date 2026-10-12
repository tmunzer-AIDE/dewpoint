# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4 recovery, task 10: `abandon_start`, an operator's end of a request left unresolved; never its send (design
revisions 2 and 3, ruling 4, the correction).

- A command kind, `abandon_start`, on a request whose `start_unresolved` is recorded (M3's fields: its item, its reason,
  since when), and a recovery reason, `start_abandoned`: the operator's record, which no pass clears
  (`work_settled_clear` keeps it whatever its request's state; 0055's text otherwise).
- `operator_commands.evidence` up to 4,000 characters: an abandonment's evidence is structured (its identifiers, the
  Temporal response its operator saw and when, their rationale), canonical JSON. The API keeps the M3 kinds' 500.

What abandonment does is the leader's (`commands._abandon_start`): the request `dead` (`start_abandoned`), its run
failed, the reason moved; the blocker, the evidence and the keys untouched.

One transaction, Alembic's own, each lock wait bounded (5 s). Its downgrade refuses while an abandonment or its reason
is kept, its locks taken before it checks."""

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
REASONS_0055 = (
    "start_after_end",
    "start_history_missing",
    "start_unresolved",
    "run_history_missing",
    "slot_history_missing",
    "subrun_history_missing",
    "start_over_limit",
    "late_start",
    "late_start_unmatched",
)
REASONS = (*REASONS_0055, "start_abandoned")
COMMANDS_0058 = ("'record_lost_run', 'record_lost_subrun', 'release_lost_slot', 'settle_ended', 'release_held', "
                 "'release_held_many', 'inspect_unresolved_send'")  # fmt: skip


def _reasons(values: tuple[str, ...]) -> list[str]:
    within = ", ".join(f"'{v}'" for v in values)
    return [f"ALTER TABLE {table} DROP CONSTRAINT {table}_reason, ADD CONSTRAINT {table}_reason "
            f"CHECK (reason IN ({within}))" for table in ("recovery_items", "operator_commands")]  # fmt: skip


def _kinds(abandon: bool) -> str:
    kinds = f"{COMMANDS_0058}, 'abandon_start'" if abandon else COMMANDS_0058
    return (f"ALTER TABLE operator_commands DROP CONSTRAINT operator_commands_kind, ADD CONSTRAINT "
            f"operator_commands_kind CHECK (kind IN ({kinds}))")  # fmt: skip


# 0055's text, exactly; then an abandonment's record kept as an operator's (no pass clears it)
SETTLED_0055 = """CREATE OR REPLACE FUNCTION work_settled_clear(max_rows integer) RETURNS integer
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
          WHEN 'start_over_limit' THEN EXISTS (SELECT 1 FROM runs u WHERE u.id = i.item_id
                                                 AND u.tenant_id = i.tenant_id AND u.status = 'running')
          WHEN 'late_start' THEN true
          WHEN 'late_start_unmatched' THEN true
          ELSE EXISTS (SELECT 1 FROM run_requests q WHERE q.id = i.item_id AND q.tenant_id = i.tenant_id
                         AND q.status = 'starting') END) LIMIT max_rows)
    RETURNING 1
  )
  SELECT ((SELECT count(*) FROM failures) + (SELECT count(*) FROM reasons))::integer
$$"""
SETTLED = SETTLED_0055.replace(
    "          WHEN 'late_start_unmatched' THEN true\n",
    "          WHEN 'late_start_unmatched' THEN true\n          WHEN 'start_abandoned' THEN true\n",
)
EVIDENCE = "ALTER TABLE operator_commands ALTER COLUMN evidence TYPE varchar(4000)"
EVIDENCE_0050 = "ALTER TABLE operator_commands ALTER COLUMN evidence TYPE varchar(500)"

# Taken before the refusal checks, in the order an abandonment writes them (its command, then its reason)
LOCKED = "LOCK TABLE operator_commands, recovery_items IN ACCESS EXCLUSIVE MODE"
REFUSE_DOWNGRADE = """DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM operator_commands WHERE kind = 'abandon_start' OR reason = 'start_abandoned')
     OR EXISTS (SELECT 1 FROM recovery_items WHERE reason = 'start_abandoned') THEN
    RAISE EXCEPTION '0059 refused: an abandonment or its record is kept (an operator''s, never dropped)';
  END IF;
END $$"""


def upgrade() -> None:
    for statement in (LOCK_TIMEOUT, _kinds(abandon=True), *_reasons(REASONS), EVIDENCE, SETTLED):
        op.execute(statement)


def downgrade() -> None:
    for statement in (LOCK_TIMEOUT, LOCKED, REFUSE_DOWNGRADE, SETTLED_0055, EVIDENCE_0050, *_reasons(REASONS_0055),
                      _kinds(abandon=False)):  # fmt: skip
        op.execute(statement)
