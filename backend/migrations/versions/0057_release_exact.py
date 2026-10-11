# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4 recovery, task 8: a held item's release is a command its operator confirms, bound to the exact holds it
showed (design revisions 7 and 8 §1; the owner's ruling on revision 6: no direct release by the API's role).

- **A hold's token:** `work_failures.hold_id`, from the sequence `work_hold_ids`, set by a trigger in the statement that
  sets `held_at` from NULL, by whatever writes it (older dispatchers included); kept while the hold lasts, whatever an
  update says; NULL when not held (`work_failures_held_token`). A hold that clears and recurs gets a new one, never a
  token reused. The holds of the day are given theirs here.
- **Two command kinds:** `release_held` (a held work's kind and its item) and `release_held_many` (a kind, `held_before`,
  `max_holds`, 1,000 at most), explicit nullable columns with a check per kind (`operator_commands_fields`): a release
  names no recovery reason, and the M3 kinds no release field.
- **The snapshot** (`operator_command_holds`): the holds a release command showed, recorded once, by
  `operator_command_holds_snapshot(command)` (the API's): the command's own selection, made in the database, never rows
  the API names, and only while it's pending and unconfirmed. Its tenant's, fenced by the erasure as every tenant table.
- **The digest covers it** (`operator_command_canonical`, replaced): a release command's fields and its holds, sorted,
  each with its token. The M3 kinds' text is unchanged byte for byte, so their confirmations still hold.
- **The leader's release** (`work_failures_release_exact(command)`, `dewpoint_dispatch`'s alone): each snapshot hold
  still held under its token is deleted (`released`); one settled since is `not_held`, one held again since is
  `hold_changed`; nothing takes a missing one's place, and no other kind's hold is touched.
- **Dropped:** `work_failure_release` and `work_failures_release_many`, the API's direct releases. `work_failures_held`
  returns each hold's token.

One transaction, Alembic's own, each lock wait bounded (5 s). Its downgrade refuses while a release command or a
snapshot is kept, its locks taken before it checks."""

from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
WORK = "'dispatch', 'reconcile_starting', 'reconcile_open', 'reconcile_slot', 'cancel', 'match', 'subrun'"
COMMANDS_0050 = "'record_lost_run', 'record_lost_subrun', 'release_lost_slot', 'settle_ended'"
RELEASES = "'release_held', 'release_held_many'"
RELEASE_MAX = 1000

HOLDS = [
    "CREATE SEQUENCE work_hold_ids",
    "ALTER TABLE work_failures ADD COLUMN hold_id bigint NULL",
    """CREATE FUNCTION work_failures_hold_id() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF NEW.held_at IS NULL THEN
    NEW.hold_id := NULL;
  ELSIF TG_OP = 'INSERT' OR OLD.hold_id IS NULL THEN  -- newly held (not held, its token NULL)
    NEW.hold_id := nextval('work_hold_ids');
  ELSE
    NEW.hold_id := OLD.hold_id;  -- the same hold: its token kept
  END IF;
  RETURN NEW;
END $$""",
    "REVOKE ALL ON FUNCTION work_failures_hold_id() FROM PUBLIC",
    "CREATE TRIGGER work_failures_hold_id BEFORE INSERT OR UPDATE ON work_failures FOR EACH ROW "
    "EXECUTE FUNCTION work_failures_hold_id()",
    "UPDATE work_failures SET held_at = held_at WHERE held_at IS NOT NULL",  # each hold so far, its token
    "ALTER TABLE work_failures ADD CONSTRAINT work_failures_held_token CHECK ((held_at IS NULL) = (hold_id IS NULL))",
]
COMMAND_FIELDS = [
    "ALTER TABLE operator_commands ADD COLUMN work_kind text NULL, ADD COLUMN held_before timestamptz NULL, "
    "ADD COLUMN max_holds integer NULL, ALTER COLUMN item_id DROP NOT NULL, ALTER COLUMN reason DROP NOT NULL, "
    "ALTER COLUMN incident_since DROP NOT NULL",
    "ALTER TABLE operator_commands DROP CONSTRAINT operator_commands_kind, ADD CONSTRAINT operator_commands_kind "
    f"CHECK (kind IN ({COMMANDS_0050}, {RELEASES}))",
    f"ALTER TABLE operator_commands ADD CONSTRAINT operator_commands_work_kind CHECK (work_kind IN ({WORK}))",
    f"""ALTER TABLE operator_commands ADD CONSTRAINT operator_commands_fields CHECK (CASE kind
  WHEN 'release_held' THEN item_id IS NOT NULL AND work_kind IS NOT NULL AND held_before IS NULL AND max_holds IS NULL
    AND reason IS NULL AND incident_since IS NULL
  WHEN 'release_held_many' THEN item_id IS NULL AND work_kind IS NOT NULL AND held_before IS NOT NULL
    AND max_holds BETWEEN 1 AND {RELEASE_MAX} AND reason IS NULL AND incident_since IS NULL
  ELSE item_id IS NOT NULL AND reason IS NOT NULL AND incident_since IS NOT NULL AND work_kind IS NULL
    AND held_before IS NULL AND max_holds IS NULL END)""",
    "GRANT SELECT (work_kind, held_before, max_holds), INSERT (work_kind, held_before, max_holds) ON operator_commands "
    "TO dewpoint_api",
]
SNAPSHOT = [
    # A key between tenant tables names the tenant (0035's rule): a snapshot never names another tenant's command
    "ALTER TABLE operator_commands ADD CONSTRAINT operator_commands_tenant_key UNIQUE (tenant_id, id)",
    """CREATE TABLE operator_command_holds (
  command_id uuid NOT NULL,
  tenant_id uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
  kind text NOT NULL,
  item_id uuid NOT NULL,
  hold_id bigint NOT NULL,
  PRIMARY KEY (command_id, tenant_id, item_id, kind),
  CONSTRAINT operator_command_holds_command FOREIGN KEY (tenant_id, command_id)
    REFERENCES operator_commands (tenant_id, id) ON DELETE CASCADE
)""",
    "ALTER TABLE operator_command_holds ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE operator_command_holds FORCE ROW LEVEL SECURITY",
    "CREATE POLICY operator_command_holds_scope ON operator_command_holds TO dewpoint_dispatch, dewpoint_retention "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "CREATE TRIGGER operator_command_holds_fence BEFORE INSERT ON operator_command_holds FOR EACH ROW "
    "EXECUTE FUNCTION tenant_insert_fence()",
    """CREATE FUNCTION operator_command_holds_snapshot(command_id uuid)
RETURNS TABLE (kind text, item_id uuid, hold_id bigint, held_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
#variable_conflict use_column
DECLARE
  v operator_commands%ROWTYPE;
  v_limit integer;
BEGIN
  SELECT * INTO v FROM operator_commands c WHERE c.id = $1 AND c.status = 'pending' FOR UPDATE;
  IF NOT FOUND OR v.kind NOT IN ('release_held', 'release_held_many') OR v.tenant_id IS DISTINCT FROM app_tenant_id() THEN
    RAISE EXCEPTION 'no pending release command % in this tenant', $1 USING ERRCODE = 'object_not_in_prerequisite_state';
  END IF;
  IF EXISTS (SELECT 1 FROM operator_confirmations x WHERE x.command_id = $1)
     OR EXISTS (SELECT 1 FROM operator_command_holds h WHERE h.command_id = $1) THEN
    RAISE EXCEPTION 'command %''s holds are recorded already', $1 USING ERRCODE = 'object_not_in_prerequisite_state';
  END IF;
  v_limit := coalesce(v.max_holds, 1);  -- a single release's one hold
  INSERT INTO operator_command_holds (command_id, tenant_id, kind, item_id, hold_id)
  SELECT $1, f.tenant_id, f.kind, f.item_id, f.hold_id FROM work_failures f
   WHERE f.tenant_id = v.tenant_id AND f.kind = v.work_kind AND f.held_at IS NOT NULL
     AND (v.kind = 'release_held_many' OR f.item_id = v.item_id)
     AND (v.held_before IS NULL OR f.held_at < v.held_before)
   ORDER BY f.held_at, f.item_id
   LIMIT v_limit;
  RETURN QUERY
  SELECT h.kind, h.item_id, h.hold_id, f.held_at FROM operator_command_holds h
    JOIN work_failures f ON f.tenant_id = h.tenant_id AND f.kind = h.kind AND f.item_id = h.item_id
   WHERE h.command_id = $1
   ORDER BY f.held_at, h.item_id;
END $$""",
    "REVOKE ALL ON FUNCTION operator_command_holds_snapshot(uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION operator_command_holds_snapshot(uuid) TO dewpoint_api",
    # What a recorded release showed, read again (an idempotent request's answer): its tenant's alone
    """CREATE FUNCTION operator_command_holds_shown(command_id uuid) RETURNS TABLE (kind text, item_id uuid, hold_id bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT h.kind, h.item_id, h.hold_id FROM operator_command_holds h
   WHERE h.command_id = $1 AND h.tenant_id = app_tenant_id() ORDER BY h.kind, h.item_id
$$""",
    "REVOKE ALL ON FUNCTION operator_command_holds_shown(uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION operator_command_holds_shown(uuid) TO dewpoint_api",
    """CREATE FUNCTION work_failures_release_exact(command_id uuid) RETURNS TABLE (item_id uuid, kind text, result text)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  WITH shown AS (
    SELECT h.tenant_id, h.kind, h.item_id, h.hold_id FROM operator_command_holds h
      JOIN operator_commands c ON c.id = h.command_id
     WHERE h.command_id = $1 AND c.status = 'pending' AND c.kind IN ('release_held', 'release_held_many')
  ), gone AS (
    DELETE FROM work_failures f USING shown s
     WHERE f.tenant_id = s.tenant_id AND f.kind = s.kind AND f.item_id = s.item_id AND f.hold_id = s.hold_id
       AND f.held_at IS NOT NULL
    RETURNING f.tenant_id, f.kind, f.item_id
  )
  SELECT s.item_id, s.kind, CASE
    WHEN EXISTS (SELECT 1 FROM gone g WHERE g.tenant_id = s.tenant_id AND g.kind = s.kind AND g.item_id = s.item_id)
      THEN 'released'
    WHEN EXISTS (SELECT 1 FROM work_failures f WHERE f.tenant_id = s.tenant_id AND f.kind = s.kind
                  AND f.item_id = s.item_id AND f.held_at IS NOT NULL)
      THEN 'hold_changed'
    ELSE 'not_held' END
  FROM shown s ORDER BY s.kind, s.item_id
$$""",
    "REVOKE ALL ON FUNCTION work_failures_release_exact(uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION work_failures_release_exact(uuid) TO dewpoint_dispatch",
]
# 0056's text, then (a release's alone) its fields and its holds, sorted, each with its token
CANONICAL = r"""CREATE OR REPLACE FUNCTION operator_command_canonical(command_id uuid) RETURNS text
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
    'idempotency_key: ' || coalesce(to_json(c.idempotency_key)::text, 'null'),
    CASE WHEN c.kind IN ('release_held', 'release_held_many') THEN concat_ws(E'\n',
      'work_kind: ' || coalesce(to_json(c.work_kind)::text, 'null'),
      'held_before: ' || coalesce(to_char(c.held_before AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), 'null'),
      'max_holds: ' || coalesce(c.max_holds::text, 'null'),
      'holds: ' || (SELECT count(*) FROM operator_command_holds h WHERE h.command_id = c.id)::text,
      (SELECT string_agg(format('hold: %s %s %s %s', h.tenant_id, to_json(h.kind)::text, h.item_id, h.hold_id), E'\n'
                         ORDER BY h.tenant_id, h.kind, h.item_id, h.hold_id)
         FROM operator_command_holds h WHERE h.command_id = c.id)) END)
  FROM operator_commands c WHERE c.id = $1
$$"""
CANONICAL_0056 = r"""CREATE OR REPLACE FUNCTION operator_command_canonical(command_id uuid) RETURNS text
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
$$"""
HELD = """CREATE FUNCTION work_failures_held(max_rows integer)
RETURNS TABLE (tenant_id uuid, kind text, item_id uuid, errors integer, last_error text, held_at timestamptz,
               hold_id bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT f.tenant_id, f.kind::text, f.item_id, f.errors, f.last_error::text, f.held_at, f.hold_id FROM work_failures f
  WHERE f.held_at IS NOT NULL
  ORDER BY f.held_at, f.tenant_id, f.item_id, f.kind
  LIMIT max_rows
$$"""
DIRECT = [  # the API's own releases, gone
    "DROP FUNCTION work_failure_release(text, uuid)",
    "DROP FUNCTION work_failures_release_many(text, timestamptz, integer)",
    "DROP FUNCTION work_failures_held(integer)",
    HELD,
    "REVOKE ALL ON FUNCTION work_failures_held(integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION work_failures_held(integer) TO dewpoint_api",
]

# 0050's, restored by the downgrade (its text, its grants)
DIRECT_0050 = [
    "DROP FUNCTION work_failures_held(integer)",
    """CREATE FUNCTION work_failure_release(released_kind text, item uuid) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  WITH gone AS (
    DELETE FROM work_failures f
     WHERE f.tenant_id = app_tenant_id() AND f.kind = released_kind AND f.item_id = item AND f.held_at IS NOT NULL
    RETURNING 1
  )
  SELECT EXISTS (SELECT 1 FROM gone)
$$""",
    """CREATE FUNCTION work_failures_release_many(held_kind text, held_before timestamptz, max_rows integer)
RETURNS TABLE (item_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  WITH gone AS (
    DELETE FROM work_failures f WHERE (f.tenant_id, f.item_id, f.kind) IN (
      SELECT w.tenant_id, w.item_id, w.kind FROM work_failures w
      WHERE w.tenant_id = app_tenant_id() AND w.kind = held_kind AND w.held_at IS NOT NULL AND w.held_at < held_before
      ORDER BY w.held_at, w.item_id
      LIMIT least(max_rows, 1000))
    RETURNING f.item_id, f.held_at
  )
  SELECT gone.item_id FROM gone ORDER BY gone.held_at, gone.item_id
$$""",
    """CREATE FUNCTION work_failures_held(max_rows integer)
RETURNS TABLE (tenant_id uuid, kind text, item_id uuid, errors integer, last_error text, held_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT f.tenant_id, f.kind::text, f.item_id, f.errors, f.last_error::text, f.held_at FROM work_failures f
  WHERE f.held_at IS NOT NULL
  ORDER BY f.held_at, f.tenant_id, f.item_id, f.kind
  LIMIT max_rows
$$""",
    "REVOKE ALL ON FUNCTION work_failure_release(text, uuid), work_failures_release_many(text, timestamptz, integer), "
    "work_failures_held(integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION work_failure_release(text, uuid), work_failures_held(integer), "
    "work_failures_release_many(text, timestamptz, integer) TO dewpoint_api",
]
# Taken before the refusal checks, in the order a release is recorded (its command, then its snapshot, read from the
# holds): one committed while the downgrade waits is seen
LOCKED = "LOCK TABLE operator_commands, operator_command_holds, work_failures IN ACCESS EXCLUSIVE MODE"
REFUSE_DOWNGRADE = f"""DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM operator_commands WHERE kind IN ({RELEASES}))
     OR EXISTS (SELECT 1 FROM operator_command_holds) THEN
    RAISE EXCEPTION '0057 refused: a release command or its holds are kept (before 0057 neither has a place)';
  END IF;
END $$"""


def upgrade() -> None:
    for statement in (LOCK_TIMEOUT, *HOLDS, *COMMAND_FIELDS, *SNAPSHOT, CANONICAL, *DIRECT):
        op.execute(statement)


def downgrade() -> None:
    for statement in (LOCK_TIMEOUT, LOCKED, REFUSE_DOWNGRADE, CANONICAL_0056, *DIRECT_0050):
        op.execute(statement)
    op.execute("DROP FUNCTION work_failures_release_exact(uuid)")
    op.execute("DROP FUNCTION operator_command_holds_shown(uuid)")
    op.execute("DROP FUNCTION operator_command_holds_snapshot(uuid)")
    op.execute("DROP TABLE operator_command_holds")
    op.execute("ALTER TABLE operator_commands DROP CONSTRAINT operator_commands_tenant_key")
    op.execute("ALTER TABLE operator_commands DROP CONSTRAINT operator_commands_fields, "
               "DROP CONSTRAINT operator_commands_work_kind, DROP CONSTRAINT operator_commands_kind, "
               f"ADD CONSTRAINT operator_commands_kind CHECK (kind IN ({COMMANDS_0050})), "
               "ALTER COLUMN item_id SET NOT NULL, ALTER COLUMN reason SET NOT NULL, "
               "ALTER COLUMN incident_since SET NOT NULL, DROP COLUMN work_kind, DROP COLUMN held_before, "
               "DROP COLUMN max_holds")  # fmt: skip
    op.execute("ALTER TABLE work_failures DROP CONSTRAINT work_failures_held_token")
    op.execute("DROP TRIGGER work_failures_hold_id ON work_failures")
    op.execute("DROP FUNCTION work_failures_hold_id()")
    op.execute("ALTER TABLE work_failures DROP COLUMN hold_id")
    op.execute("DROP SEQUENCE work_hold_ids")
