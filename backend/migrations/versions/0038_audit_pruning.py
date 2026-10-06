# SPDX-License-Identifier: Apache-2.0
"""Audit pruning (engine 2b spec §10.2; ruling D5): past the platform's audit retention, a scope's oldest entries are
deleted through a checkpoint, the last entry pruned, which the anchor job anchors off the database first and records
in `audit_checkpoints`; the verifier starts each chain from its latest checkpoint.

`audit_prune()` alone deletes, as the table's owner: through a recorded checkpoint that matches its entry, of an entry
older than the retention it's given, never one under 30 days, holding the scope's append lock. The append-only trigger
lets a delete through only inside it. A scope pruned whole goes on from its checkpoint: `audit_append()` chains its
next entry to it. Until an off-host anchor sink exists (#3, 2b-4b), it refuses outside a development deployment: an anchor
on the database's own host can't show that a privileged operator didn't prune, rewrite and re-anchor."""

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

UPGRADE = [
    """CREATE TABLE audit_checkpoints (
  scope text NOT NULL,
  seq bigint NOT NULL,
  hash bytea NOT NULL,
  sink text NOT NULL,
  sink_ref text NOT NULL,
  anchored_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope, seq)
)""",
    "REVOKE ALL ON audit_checkpoints FROM PUBLIC",
    "GRANT SELECT ON audit_checkpoints TO dewpoint_api, dewpoint_admin, dewpoint_auditor",
    "GRANT INSERT ON audit_checkpoints TO dewpoint_auditor",
    """CREATE OR REPLACE FUNCTION audit_reject() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- audit_prune() alone deletes, as the owner, with its flag set for its own statement: no other role may delete
  IF TG_OP = 'DELETE' AND current_setting('dewpoint.audit_pruning', true) = 'on' THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'audit_log is append-only';
END $$""",
    r"""CREATE OR REPLACE FUNCTION audit_append(p_tenant uuid, p_actor uuid, p_action text, p_target_type text, p_target_id text,
                             p_details jsonb) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_scope text := COALESCE(p_tenant::text, 'platform');
  v_prev bytea;
  v_seq bigint;
  v_ts timestamptz := date_trunc('microseconds', clock_timestamp());
  v_tt text := COALESCE(p_target_type, '');
  v_tid text := COALESCE(p_target_id, '');
  v_details jsonb := COALESCE(p_details, '{}'::jsonb);
BEGIN
  IF p_tenant IS NOT NULL AND p_tenant IS DISTINCT FROM app_tenant_id() THEN
    RAISE EXCEPTION 'audit tenant mismatch';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('audit:' || v_scope, 0));
  SELECT hash INTO v_prev FROM audit_log WHERE scope = v_scope ORDER BY seq DESC LIMIT 1;
  IF v_prev IS NULL THEN  -- a scope pruned whole goes on from its checkpoint, the last entry pruned
    SELECT hash INTO v_prev FROM audit_checkpoints WHERE scope = v_scope ORDER BY seq DESC LIMIT 1;
  END IF;
  v_prev := COALESCE(v_prev, decode(repeat('00', 32), 'hex'));
  v_seq := nextval(pg_get_serial_sequence('audit_log', 'seq'));
  INSERT INTO audit_log(seq, scope, tenant_id, actor_id, action, target_type, target_id, details, created_at,
                        prev_hash, hash)
  VALUES (v_seq, v_scope, p_tenant, p_actor, p_action, v_tt, v_tid, v_details, v_ts, v_prev,
          sha256(v_prev || convert_to(audit_canonical(v_seq, v_scope, p_actor, p_action, v_tt, v_tid, v_details, v_ts), 'UTF8')));
  RETURN v_seq;
END $$""",
    """CREATE FUNCTION audit_pruning_enabled() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp AS $$
  SELECT COALESCE((SELECT environment = 'development' FROM platform_settings WHERE id = 1), false)
$$""",
    "REVOKE EXECUTE ON FUNCTION audit_pruning_enabled() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION audit_pruning_enabled() TO dewpoint_auditor",
    """CREATE FUNCTION audit_prune(p_scope text, p_through bigint, p_older_than_days int) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_count bigint;
BEGIN
  IF NOT audit_pruning_enabled() THEN
    RAISE EXCEPTION 'audit pruning is disabled outside a development deployment until an off-host anchor sink (#3)';
  END IF;
  IF p_older_than_days < 30 THEN
    RAISE EXCEPTION 'an audit retention under 30 days';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM audit_checkpoints c JOIN audit_log l ON l.scope = c.scope AND l.seq = c.seq
                 AND l.hash = c.hash WHERE c.scope = p_scope AND c.seq = p_through) THEN
    RAISE EXCEPTION 'no recorded checkpoint matches that entry';
  END IF;
  IF (SELECT created_at FROM audit_log WHERE scope = p_scope AND seq = p_through)
     >= statement_timestamp() - make_interval(days => p_older_than_days) THEN
    RAISE EXCEPTION 'that entry is within the audit retention';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('audit:' || p_scope, 0));  -- appends to the scope wait
  PERFORM set_config('dewpoint.audit_pruning', 'on', true);
  DELETE FROM audit_log WHERE scope = p_scope AND seq <= p_through;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  PERFORM set_config('dewpoint.audit_pruning', 'off', true);
  RETURN v_count;
END $$""",
    "REVOKE EXECUTE ON FUNCTION audit_prune(text, bigint, int) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION audit_prune(text, bigint, int) TO dewpoint_auditor",
]
DOWNGRADE = [
    "DROP FUNCTION audit_prune(text, bigint, int)",
    r"""CREATE OR REPLACE FUNCTION audit_append(p_tenant uuid, p_actor uuid, p_action text, p_target_type text, p_target_id text,
                             p_details jsonb) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_scope text := COALESCE(p_tenant::text, 'platform');
  v_prev bytea;
  v_seq bigint;
  v_ts timestamptz := date_trunc('microseconds', clock_timestamp());
  v_tt text := COALESCE(p_target_type, '');
  v_tid text := COALESCE(p_target_id, '');
  v_details jsonb := COALESCE(p_details, '{}'::jsonb);
BEGIN
  IF p_tenant IS NOT NULL AND p_tenant IS DISTINCT FROM app_tenant_id() THEN
    RAISE EXCEPTION 'audit tenant mismatch';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('audit:' || v_scope, 0));
  SELECT hash INTO v_prev FROM audit_log WHERE scope = v_scope ORDER BY seq DESC LIMIT 1;
  v_prev := COALESCE(v_prev, decode(repeat('00', 32), 'hex'));
  v_seq := nextval(pg_get_serial_sequence('audit_log', 'seq'));
  INSERT INTO audit_log(seq, scope, tenant_id, actor_id, action, target_type, target_id, details, created_at,
                        prev_hash, hash)
  VALUES (v_seq, v_scope, p_tenant, p_actor, p_action, v_tt, v_tid, v_details, v_ts, v_prev,
          sha256(v_prev || convert_to(audit_canonical(v_seq, v_scope, p_actor, p_action, v_tt, v_tid, v_details, v_ts), 'UTF8')));
  RETURN v_seq;
END $$""",
    "DROP FUNCTION audit_pruning_enabled()",
    """CREATE OR REPLACE FUNCTION audit_reject() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$""",
    "DROP TABLE audit_checkpoints",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
