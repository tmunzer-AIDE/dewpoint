# SPDX-License-Identifier: Apache-2.0
"""audit: append-only hash-chained log, anchors, dedicated auditor role"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# One statement per execute (asyncpg cannot run multi-statement strings).
UPGRADE = [
    r"""CREATE TABLE audit_log (
  seq bigserial PRIMARY KEY,
  scope text NOT NULL,
  tenant_id uuid,
  actor_id uuid,
  action text NOT NULL,
  target_type text NOT NULL DEFAULT '',
  target_id text NOT NULL DEFAULT '',
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL,
  prev_hash bytea NOT NULL,
  hash bytea NOT NULL
)""",
    r"""CREATE INDEX ix_audit_scope_seq ON audit_log(scope, seq DESC)""",
    r"""CREATE INDEX ix_audit_tenant_seq ON audit_log(tenant_id, seq DESC)""",
    r"""CREATE TABLE audit_anchors (
  id bigserial PRIMARY KEY,
  scope text NOT NULL,
  seq bigint NOT NULL,
  hash bytea NOT NULL,
  anchored_at timestamptz NOT NULL DEFAULT now(),
  sink text NOT NULL,
  sink_ref text NOT NULL,
  UNIQUE (scope, seq)
)""",
    r"""CREATE FUNCTION audit_canonical(p_seq bigint, p_scope text, p_actor uuid, p_action text, p_tt text, p_tid text,
                                p_details jsonb, p_ts timestamptz) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT concat_ws('|', p_seq, p_scope, COALESCE(p_actor::text, ''), p_action, p_tt, p_tid, p_details::text,
                   to_char(p_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
$$""",
    r"""CREATE FUNCTION audit_append(p_tenant uuid, p_actor uuid, p_action text, p_target_type text, p_target_id text,
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
    r"""CREATE FUNCTION audit_reject() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$""",
    r"""CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_reject()""",
    r"""CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_log FOR EACH STATEMENT EXECUTE FUNCTION audit_reject()""",
    r"""ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY""",
    r"""-- deliberately not FORCE (see plan)
CREATE POLICY audit_tenant_read ON audit_log FOR SELECT USING (tenant_id = app_tenant_id())""",
    r"""DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dewpoint_auditor') THEN CREATE ROLE dewpoint_auditor NOLOGIN; END IF;
END $$""",
    r"""GRANT USAGE ON SCHEMA public TO dewpoint_auditor""",
    r"""CREATE POLICY audit_auditor_read ON audit_log FOR SELECT TO dewpoint_auditor USING (true)""",
    r"""REVOKE ALL ON audit_log, audit_anchors FROM PUBLIC""",
    r"""GRANT SELECT ON audit_log TO dewpoint_api, dewpoint_admin, dewpoint_auditor""",
    r"""GRANT SELECT, INSERT ON audit_anchors TO dewpoint_auditor""",
    r"""GRANT USAGE ON SEQUENCE audit_anchors_id_seq TO dewpoint_auditor""",
    r"""REVOKE EXECUTE ON FUNCTION audit_append(uuid, uuid, text, text, text, jsonb) FROM PUBLIC""",
    r"""GRANT EXECUTE ON FUNCTION audit_append(uuid, uuid, text, text, text, jsonb)
  TO dewpoint_api, dewpoint_worker, dewpoint_dispatch, dewpoint_ingress, dewpoint_admin""",
]

DOWNGRADE = [
    "DROP TABLE audit_anchors",
    "DROP TABLE audit_log",
    "DROP FUNCTION audit_append(uuid, uuid, text, text, text, jsonb)",
    "DROP FUNCTION audit_canonical(bigint, text, uuid, text, text, text, jsonb, timestamptz)",
    "DROP FUNCTION audit_reject()",
    "REVOKE ALL ON SCHEMA public FROM dewpoint_auditor",
    "DROP ROLE IF EXISTS dewpoint_auditor",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
