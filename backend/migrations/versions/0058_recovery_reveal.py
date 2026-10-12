# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4 recovery, task 9: unresolved sends counted for a platform admin, and their identifiers revealed only to an
operator's own recovery login, audited (design revision 5 §4, revision 6 §2; the plan's ruling 6).

- `admin_session(token)`: the caller's session, checked by the database itself: the raw token's digest (`sessions`
  keeps PostgreSQL's `sha256`), unrevoked, unexpired, `active`, with a second factor among its methods, of an active
  platform admin; its user's id, or `insufficient_privilege`. Internal: no grant.
- `unresolved_sends_counts(token)` (`dewpoint_api`'s): per blocker state, the requests and their open sends and the
  oldest; and the incomplete erasures of tenants a blocker names (`erasures_held`: what phase D's hold will hold). No
  identifier.
- A command kind, `inspect_unresolved_send`: the reveal's own, naming one request (no recovery reason). The leader
  never carries it out (`pending_commands` passes it by within its hour; one left past it, the leader refuses
  `expired`, so it holds its request no longer).
- `recovery.unresolved_send_reveal(command)` (`dewpoint_recovery`'s): before anything, the command is a pending
  inspection within its hour, confirmed, its digest the confirmed one, and the caller the confirming login, still
  mapped to its actor and unrevoked (ruling 6); then its audit entry, in the same transaction (its failure returns
  nothing); then that blocker's identifiers and each of its sends; the command applied.

One transaction, Alembic's own, each lock wait bounded (5 s). Its downgrade refuses while an inspection is kept, its
lock taken before it checks."""

from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
CONFIRM_WITHIN = "interval '1 hour'"  # 0056's: a command's hour, from when it was asked
COMMANDS_0057 = ("'record_lost_run', 'record_lost_subrun', 'release_lost_slot', 'settle_ended', 'release_held', "
                 "'release_held_many'")  # fmt: skip
RELEASE_MAX = 1000
INSPECT = "inspect_unresolved_send"


def _fields(inspect: bool) -> str:
    """`operator_commands_fields`, 0057's, and (`inspect`) an inspection's: a request, no reason, no release field."""
    inspection = (f"\n  WHEN '{INSPECT}' THEN item_id IS NOT NULL AND reason IS NULL AND incident_since IS NULL "
                  "AND work_kind IS NULL AND held_before IS NULL AND max_holds IS NULL") if inspect else ""  # fmt: skip
    return f"""ALTER TABLE operator_commands DROP CONSTRAINT operator_commands_fields, ADD CONSTRAINT operator_commands_fields CHECK (CASE kind
  WHEN 'release_held' THEN item_id IS NOT NULL AND work_kind IS NOT NULL AND held_before IS NULL AND max_holds IS NULL
    AND reason IS NULL AND incident_since IS NULL
  WHEN 'release_held_many' THEN item_id IS NULL AND work_kind IS NOT NULL AND held_before IS NOT NULL
    AND max_holds BETWEEN 1 AND {RELEASE_MAX} AND reason IS NULL AND incident_since IS NULL{inspection}
  ELSE item_id IS NOT NULL AND reason IS NOT NULL AND incident_since IS NOT NULL AND work_kind IS NULL
    AND held_before IS NULL AND max_holds IS NULL END)"""


def _kinds(inspect: bool) -> str:
    kinds = f"{COMMANDS_0057}, '{INSPECT}'" if inspect else COMMANDS_0057
    return (f"ALTER TABLE operator_commands DROP CONSTRAINT operator_commands_kind, ADD CONSTRAINT "
            f"operator_commands_kind CHECK (kind IN ({kinds}))")  # fmt: skip


FUNCTIONS = [
    """CREATE FUNCTION admin_session(token text) RETURNS uuid
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
DECLARE
  v_user uuid;
BEGIN
  SELECT s.user_id INTO v_user FROM sessions s JOIN users u ON u.id = s.user_id
   WHERE $1 IS NOT NULL AND s.token_hash = sha256(convert_to($1, 'UTF8')) AND s.revoked_at IS NULL
     AND s.expires_at > statement_timestamp() AND s.state = 'active'
     AND s.auth_methods && ARRAY['totp', 'recovery', 'passkey']::varchar[]
     AND u.is_active AND u.is_platform_admin;
  IF v_user IS NULL THEN
    RAISE EXCEPTION 'not a platform admin''s session' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN v_user;
END $$""",
    "REVOKE ALL ON FUNCTION admin_session(text) FROM PUBLIC",
    """CREATE FUNCTION unresolved_sends_counts(token text)
RETURNS TABLE (state text, requests bigint, open_sends bigint, oldest timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
#variable_conflict use_column
BEGIN
  PERFORM admin_session($1);
  RETURN QUERY
  SELECT k.state, count(b.request_id), coalesce(sum(o.open), 0)::bigint, min(b.first_at)
    FROM (VALUES ('pending'), ('unresolved'), ('identified'), ('deleted_open')) k(state)
    LEFT JOIN unresolved_sends b ON b.state = k.state
    LEFT JOIN LATERAL (SELECT count(*) AS open FROM start_sends x
                        WHERE x.request_id = b.request_id AND x.answer IS NULL) o ON true
   GROUP BY k.state
  UNION ALL
  SELECT 'erasures_held', count(*), NULL::bigint, min(e.requested_at) FROM tenant_erasures e
   WHERE e.completed_at IS NULL AND e.stopped_at IS NULL
     AND EXISTS (SELECT 1 FROM unresolved_sends b WHERE b.tenant_id = e.tenant_id);
END $$""",
    "REVOKE ALL ON FUNCTION unresolved_sends_counts(text) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION unresolved_sends_counts(text) TO dewpoint_api",
    f"""CREATE FUNCTION recovery.unresolved_send_reveal(command_id uuid)
RETURNS TABLE (tenant_id uuid, request_id uuid, workflow_id text, start_request_id uuid, state text,
               identified_run_id text, attempt smallint, answer text, run_id text, intent_at timestamptz,
               answered_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
#variable_conflict use_column
DECLARE
  v operator_commands%ROWTYPE;
  v_confirmed operator_confirmations%ROWTYPE;
  v_scope text;
BEGIN
  SELECT * INTO v FROM operator_commands c
   WHERE c.id = $1 AND c.status = 'pending' AND c.kind = '{INSPECT}' FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'no pending inspection %', $1 USING ERRCODE = 'object_not_in_prerequisite_state';
  END IF;
  IF v.requested_at < statement_timestamp() - {CONFIRM_WITHIN} THEN
    RAISE EXCEPTION 'command %''s hour has passed: ask again', $1 USING ERRCODE = 'object_not_in_prerequisite_state';
  END IF;
  SELECT * INTO v_confirmed FROM operator_confirmations x WHERE x.command_id = $1;
  IF NOT FOUND OR v_confirmed.digest IS DISTINCT FROM operator_command_digest($1) THEN
    RAISE EXCEPTION 'command % is not confirmed as it stands', $1 USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF v_confirmed.login <> session_user OR NOT EXISTS (
       SELECT 1 FROM recovery_operators o
        WHERE o.login = session_user AND o.user_id = v.actor_id AND o.revoked_at IS NULL) THEN
    RAISE EXCEPTION 'this login is not the confirming login, or is revoked' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM unresolved_sends b WHERE b.request_id = v.item_id AND b.tenant_id = v.tenant_id) THEN
    RAISE EXCEPTION 'no blocker for request %', v.item_id USING ERRCODE = 'no_data_found';
  END IF;
  v_scope := current_setting('app.tenant_id', true);  -- the audit entry is the command's tenant's
  PERFORM set_config('app.tenant_id', v.tenant_id::text, true);
  PERFORM audit_append(v.tenant_id, v.actor_id, 'recovery.unresolved_send.revealed', 'operator_command', $1::text,
                       jsonb_build_object('login', session_user::text, 'request_id', v.item_id::text));
  PERFORM set_config('app.tenant_id', coalesce(v_scope, ''), true);
  UPDATE operator_commands c SET status = 'applied', outcome = 'revealed', decided_at = statement_timestamp()
   WHERE c.id = $1;
  RETURN QUERY
  SELECT b.tenant_id, b.request_id, b.workflow_id, b.start_request_id, b.state, b.identified_run_id, x.attempt,
         x.answer, x.run_id, x.intent_at, x.answered_at
    FROM unresolved_sends b LEFT JOIN start_sends x ON x.request_id = b.request_id
   WHERE b.request_id = v.item_id ORDER BY x.attempt;
END $$""",
    "REVOKE ALL ON FUNCTION recovery.unresolved_send_reveal(uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION recovery.unresolved_send_reveal(uuid) TO dewpoint_recovery",
]
PENDING = f"""CREATE OR REPLACE FUNCTION pending_commands(max_rows integer) RETURNS TABLE (tenant_id uuid, command_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT c.tenant_id, c.id FROM operator_commands c WHERE c.status = 'pending'
     AND ((c.kind <> '{INSPECT}' AND EXISTS (SELECT 1 FROM operator_confirmations x WHERE x.command_id = c.id))
          OR c.requested_at < statement_timestamp() - {CONFIRM_WITHIN})
  ORDER BY c.requested_at, c.id
  LIMIT max_rows
$$"""
PENDING_0056 = f"""CREATE OR REPLACE FUNCTION pending_commands(max_rows integer) RETURNS TABLE (tenant_id uuid, command_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT c.tenant_id, c.id FROM operator_commands c WHERE c.status = 'pending'
     AND (EXISTS (SELECT 1 FROM operator_confirmations x WHERE x.command_id = c.id)
          OR c.requested_at < statement_timestamp() - {CONFIRM_WITHIN})
  ORDER BY c.requested_at, c.id
  LIMIT max_rows
$$"""

LOCKED = "LOCK TABLE operator_commands IN ACCESS EXCLUSIVE MODE"  # before the refusal checks it
REFUSE_DOWNGRADE = f"""DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM operator_commands WHERE kind = '{INSPECT}') THEN
    RAISE EXCEPTION '0058 refused: an inspection is kept (before 0058 it has no place)';
  END IF;
END $$"""


def upgrade() -> None:
    for statement in (LOCK_TIMEOUT, _kinds(inspect=True), _fields(inspect=True), *FUNCTIONS, PENDING):
        op.execute(statement)


def downgrade() -> None:
    for statement in (LOCK_TIMEOUT, LOCKED, REFUSE_DOWNGRADE, PENDING_0056):
        op.execute(statement)
    op.execute("DROP FUNCTION recovery.unresolved_send_reveal(uuid)")
    op.execute("DROP FUNCTION unresolved_sends_counts(text)")
    op.execute("DROP FUNCTION admin_session(text)")
    op.execute(_fields(inspect=False))
    op.execute(_kinds(inspect=False))
