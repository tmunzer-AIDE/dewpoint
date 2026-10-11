# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4 recovery, the final gate (the owner's ruling): the reveal re-checks its actor's authority now.

`recovery.unresolved_send_reveal(command)` (0058) checked the confirming login, still mapped to its actor and unrevoked,
but not whether that actor is still an active platform admin, as the dispatcher's leader checks for every other
command (`platform_admin_active`). One demoted or deactivated between confirming and revealing, its login not yet
revoked, is now refused before anything is audited, returned or applied. Replaced in place: the same signature, owner
and grant; nothing else changes.

One transaction, Alembic's own, each lock wait bounded (5 s): one function replaced, no table changed. Its downgrade
restores 0058's text exactly, and with it the disclosure this closes: so it refuses while any inspection is kept, any
recovery login is unrevoked, or anyone is a member of `dewpoint_recovery`, its locks taken before it checks."""

from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
REVEAL = """CREATE OR REPLACE FUNCTION recovery.unresolved_send_reveal(command_id uuid)
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
   WHERE c.id = $1 AND c.status = 'pending' AND c.kind = 'inspect_unresolved_send' FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'no pending inspection %', $1 USING ERRCODE = 'object_not_in_prerequisite_state';
  END IF;
  IF v.requested_at < statement_timestamp() - interval '1 hour' THEN
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
  IF NOT platform_admin_active(v.actor_id) THEN
    RAISE EXCEPTION 'command %''s actor is not an active platform admin', $1 USING ERRCODE = 'insufficient_privilege';
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
END $$"""
REVEAL_0058 = """CREATE OR REPLACE FUNCTION recovery.unresolved_send_reveal(command_id uuid)
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
   WHERE c.id = $1 AND c.status = 'pending' AND c.kind = 'inspect_unresolved_send' FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'no pending inspection %', $1 USING ERRCODE = 'object_not_in_prerequisite_state';
  END IF;
  IF v.requested_at < statement_timestamp() - interval '1 hour' THEN
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
END $$"""


# Before the checks: 0056's and 0058's own lock, so no inspection, mapping or confirmation lands while it looks
LOCKED = "LOCK TABLE operator_commands, recovery_operators, operator_confirmations IN ACCESS EXCLUSIVE MODE"
REFUSE_DOWNGRADE = """DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM operator_commands WHERE kind = 'inspect_unresolved_send')
     OR EXISTS (SELECT 1 FROM recovery_operators WHERE revoked_at IS NULL)
     OR EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid
                 WHERE r.rolname = 'dewpoint_recovery') THEN
    RAISE EXCEPTION '0065 refused: an inspection, an unrevoked recovery login or a member of dewpoint_recovery is kept '
                    '(0058''s reveal would disclose to an actor no longer an active platform admin)';
  END IF;
END $$"""


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute(REVEAL)


def downgrade() -> None:
    for statement in (LOCK_TIMEOUT, LOCKED, REFUSE_DOWNGRADE, REVEAL_0058):
        op.execute(statement)
