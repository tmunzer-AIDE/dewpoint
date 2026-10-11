# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4 recovery, task 6: an operator's command is carried out only once its operator confirms it through their own
recovery login (design revision 6 §3; the plan's ruling 4). M3's gap: a holder of the API's credentials could record a
command under any admin's id. The confirmation goes through a channel the API's processes don't hold.

- `recovery_operators`: a recovery login (`rcv_...`, a member of `dewpoint_recovery`) mapped to the platform user it
  is, provisioned and revoked by the database administrator (task 7), never by an application role. The leader reads it.
- `operator_command_canonical(command)`: the command's canonical text, built in the database alone: each field
  labelled, text quoted as JSON (no line of it can pass for another), NULL a fixed token, its time in UTC to the
  microsecond. Internal: no grant. `operator_command_digest(command)`, its sha256, is the leader's.
- `recovery.operator_command_show(command)`: that text and its digest, for the actor's own mapped, unrevoked login.
- `recovery.operator_command_confirm(command, digest)`: by that login, of a pending command not yet confirmed and
  asked within the hour, with the digest it was shown. It writes `operator_confirmations` and an audit entry naming the
  login, in the command's tenant's scope.
- The auditor reads the mappings and `alembic_version`: the independent monitor compares them with the administration
  recorded off the host (task 7).
- `pending_commands`: the leader picks a command once it's confirmed; one left unconfirmed past the hour, to refuse it
  `unconfirmed`, so its item may be asked again (a pending command holds its item). Never one awaiting its operator.

One transaction, Alembic's own, each lock wait bounded (5 s). Its downgrade refuses while a mapping, a confirmation or
a pending command is kept (before 0056 a pending command is carried out unconfirmed), its locks taken before it
checks."""

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
CONFIRM_WITHIN = "interval '1 hour'"  # an unconfirmed command's window, from when it was asked

TABLES = [
    """CREATE TABLE recovery_operators (
  login text PRIMARY KEY CONSTRAINT recovery_operators_login CHECK (login ~ '^rcv_[a-z0-9_]{1,59}$'),
  user_id uuid NOT NULL,
  provisioned_by text NOT NULL,
  provisioned_at timestamptz NOT NULL,
  revoked_by text NULL,
  revoked_at timestamptz NULL,
  CONSTRAINT recovery_operators_revoked CHECK ((revoked_by IS NULL) = (revoked_at IS NULL))
)""",
    # A decided command's confirmation stays with it: the command's deletion (retention, the erasure) takes it
    """CREATE TABLE operator_confirmations (
  command_id uuid PRIMARY KEY REFERENCES operator_commands (id) ON DELETE CASCADE,
  login text NOT NULL,
  user_id uuid NOT NULL,
  digest bytea NOT NULL,
  confirmed_at timestamptz NOT NULL
)""",
    "GRANT SELECT ON recovery_operators, operator_confirmations TO dewpoint_dispatch",
    # The independent monitor's (task 7): the mappings and the schema's revision, compared with the records off the host
    "GRANT SELECT ON recovery_operators, alembic_version TO dewpoint_auditor",
]
FUNCTIONS = [
    r"""CREATE FUNCTION operator_command_canonical(command_id uuid) RETURNS text
LANGUAGE sql STABLE SET search_path = public, pg_temp AS $$
  SELECT concat_ws(E'\n',
    'format: dewpoint-operator-command/1',
    'id: ' || c.id::text,
    'kind: ' || coalesce(to_json(c.kind)::text, 'null'),
    'tenant: ' || coalesce(c.tenant_id::text, 'null'),
    'item: ' || coalesce(c.item_id::text, 'null'),
    'reason: ' || coalesce(to_json(c.reason)::text, 'null'),
    'incident_since: ' || coalesce(to_char(c.incident_since AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
                                   'null'),
    'evidence: ' || coalesce(to_json(c.evidence)::text, 'null'),
    'actor: ' || coalesce(c.actor_id::text, 'null'),
    'idempotency_key: ' || coalesce(to_json(c.idempotency_key)::text, 'null'))
  FROM operator_commands c WHERE c.id = $1
$$""",
    """CREATE FUNCTION operator_command_digest(command_id uuid) RETURNS bytea
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT sha256(convert_to(operator_command_canonical($1), 'UTF8'))
$$""",
    """CREATE FUNCTION recovery.operator_command_show(command_id uuid) RETURNS TABLE (canonical text, digest bytea)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM operator_commands c JOIN recovery_operators o ON o.user_id = c.actor_id
                  WHERE c.id = $1 AND o.login = session_user AND o.revoked_at IS NULL) THEN
    RAISE EXCEPTION 'this login is not the command''s operator''s, or is revoked'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN QUERY SELECT operator_command_canonical($1), operator_command_digest($1);
END $$""",
    f"""CREATE FUNCTION recovery.operator_command_confirm(command_id uuid, digest bytea) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
DECLARE
  v_command operator_commands%ROWTYPE;
  v_user uuid;
  v_scope text;
BEGIN
  SELECT * INTO v_command FROM operator_commands c WHERE c.id = $1 AND c.status = 'pending' FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'no pending command %', $1 USING ERRCODE = 'object_not_in_prerequisite_state';
  END IF;
  SELECT o.user_id INTO v_user FROM recovery_operators o WHERE o.login = session_user AND o.revoked_at IS NULL;
  IF v_user IS NULL OR v_user <> v_command.actor_id THEN
    RAISE EXCEPTION 'this login is not the command''s operator''s, or is revoked'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF EXISTS (SELECT 1 FROM operator_confirmations x WHERE x.command_id = $1) THEN
    RAISE EXCEPTION 'command % is already confirmed', $1 USING ERRCODE = 'unique_violation';
  END IF;
  IF v_command.requested_at < statement_timestamp() - {CONFIRM_WITHIN} THEN
    RAISE EXCEPTION 'command %''s hour to be confirmed has passed: ask again', $1
      USING ERRCODE = 'object_not_in_prerequisite_state';
  END IF;
  IF $2 IS NULL OR $2 <> operator_command_digest($1) THEN
    RAISE EXCEPTION 'command % changed since it was shown: show it again', $1
      USING ERRCODE = 'invalid_parameter_value';
  END IF;
  INSERT INTO operator_confirmations (command_id, login, user_id, digest, confirmed_at)
  VALUES ($1, session_user, v_user, $2, statement_timestamp());
  v_scope := current_setting('app.tenant_id', true);  -- the audit entry is the command's tenant's
  PERFORM set_config('app.tenant_id', v_command.tenant_id::text, true);
  PERFORM audit_append(v_command.tenant_id, v_user, 'operator.command.confirmed', 'operator_command', $1::text,
                       jsonb_build_object('login', session_user::text, 'kind', v_command.kind,
                                          'item_id', v_command.item_id::text, 'digest', encode($2, 'hex')));
  PERFORM set_config('app.tenant_id', coalesce(v_scope, ''), true);
END $$""",
    "REVOKE ALL ON FUNCTION operator_command_canonical(uuid) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION operator_command_digest(uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION operator_command_digest(uuid) TO dewpoint_dispatch",
    "REVOKE ALL ON FUNCTION recovery.operator_command_show(uuid), recovery.operator_command_confirm(uuid, bytea) "
    "FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION recovery.operator_command_show(uuid), recovery.operator_command_confirm(uuid, bytea) "
    "TO dewpoint_recovery",
]
PENDING = f"""CREATE OR REPLACE FUNCTION pending_commands(max_rows integer) RETURNS TABLE (tenant_id uuid, command_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT c.tenant_id, c.id FROM operator_commands c WHERE c.status = 'pending'
     AND (EXISTS (SELECT 1 FROM operator_confirmations x WHERE x.command_id = c.id)
          OR c.requested_at < statement_timestamp() - {CONFIRM_WITHIN})
  ORDER BY c.requested_at, c.id
  LIMIT max_rows
$$"""
PENDING_0050 = """CREATE OR REPLACE FUNCTION pending_commands(max_rows integer) RETURNS TABLE (tenant_id uuid, command_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT c.tenant_id, c.id FROM operator_commands c WHERE c.status = 'pending'
  ORDER BY c.requested_at, c.id
  LIMIT max_rows
$$"""

# Taken before the refusal checks, in the order a confirmation takes them (its command, the login's mapping, then its
# record): one committed while the downgrade waits is seen
LOCKED = "LOCK TABLE operator_commands, recovery_operators, operator_confirmations IN ACCESS EXCLUSIVE MODE"
REFUSE_DOWNGRADE = """DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM recovery_operators) OR EXISTS (SELECT 1 FROM operator_confirmations)
     OR EXISTS (SELECT 1 FROM operator_commands WHERE status = 'pending') THEN
    RAISE EXCEPTION '0056 refused: a mapping, a confirmation or a pending command is kept (a pending one runs unconfirmed)';
  END IF;
END $$"""


def upgrade() -> None:
    for statement in (LOCK_TIMEOUT, *TABLES, *FUNCTIONS, PENDING):
        op.execute(statement)


def downgrade() -> None:
    for statement in (LOCK_TIMEOUT, LOCKED, REFUSE_DOWNGRADE, PENDING_0050):
        op.execute(statement)
    op.execute("REVOKE SELECT ON alembic_version FROM dewpoint_auditor")
    op.execute("DROP FUNCTION recovery.operator_command_confirm(uuid, bytea)")
    op.execute("DROP FUNCTION recovery.operator_command_show(uuid)")
    op.execute("DROP FUNCTION operator_command_digest(uuid)")
    op.execute("DROP FUNCTION operator_command_canonical(uuid)")
    op.execute("DROP TABLE operator_confirmations")
    op.execute("DROP TABLE recovery_operators")
