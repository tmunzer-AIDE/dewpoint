# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4 recovery, task 3: the blocker store, the fence against older dispatchers, and the backfill of the attempts
made before them (the owner's rulings 1, 2, 8 and 9 on the recovery plan).

- `unresolved_sends`: a request whose start sends might still create an execution, kept until they can't (its state:
  `pending` while every send is accounted for, `unresolved` once one became uncertain, `identified` once the recorded
  start request id is seen on the first run's started event, `deleted_open` for the erasure). Platform-scoped: no
  row-level security, no key to a tenant's tables, swept by neither the erasure nor retention, so it outlives both.
- `start_sends`: each counted send (its attempt, the request's `sends`), recorded in flight in the transaction that
  makes the request `starting`, and its own call's direct answer, written once.
- The fence, `run_requests_send_recorded`: a deferred constraint trigger. A transaction that makes a request `starting`,
  or counts another of its sends, commits only with that send's intent recorded in it (its `intent_xid` the
  transaction's). A dispatcher from before 0052 (status only) or from before this migration (counted, never recorded)
  can no longer commit its starting transaction, and sends only after it: it can't send. Permanent: the invariant from
  now on. The dispatcher's own holds (`Held`: back to `starting`, nothing sent) say so in their transaction
  (`dewpoint.start_held`), and are never let count a send.
- The backfill, after the fence: every unproven root execution and every request `starting` gets a `legacy_unknown`,
  `unresolved` blocker (its recorded start request id, if any), and no invented send. A legacy-unknown blocker never
  leaves the store unless the owner decides otherwise. An unproven root whose workflow id names no request stops the
  migration: it's never skipped.

One transaction, Alembic's own: the fence's trigger holds `run_requests` (SHARE ROW EXCLUSIVE) from its creation to the
commit, so no request changes between the fence and the backfill. Its writes are two new tables, one trigger and their
rows; its reads, the requests `starting` and the unproven root evidence. Each lock wait is bounded (5 s, online.py's):
one not taken in time rolls it all back. Its downgrade refuses while any blocker is left."""

from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
TABLES = [
    """CREATE TABLE unresolved_sends (
  request_id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  workflow_id text NOT NULL,
  start_request_id uuid NULL,
  legacy_unknown boolean NOT NULL DEFAULT false,
  state text NOT NULL CHECK (state IN ('pending', 'unresolved', 'identified', 'deleted_open')),
  identified_run_id text NULL,
  first_at timestamptz NOT NULL DEFAULT statement_timestamp(),
  changed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
  CONSTRAINT unresolved_sends_identity CHECK (start_request_id IS NOT NULL OR legacy_unknown),
  CONSTRAINT unresolved_sends_legacy CHECK (NOT legacy_unknown OR state <> 'pending'),
  CONSTRAINT unresolved_sends_identified CHECK (state NOT IN ('identified', 'deleted_open')
                                                OR identified_run_id IS NOT NULL))""",
    """CREATE TABLE start_sends (
  request_id uuid NOT NULL REFERENCES unresolved_sends ON DELETE CASCADE,
  attempt smallint NOT NULL CHECK (attempt BETWEEN 1 AND 10),
  intent_at timestamptz NOT NULL DEFAULT statement_timestamp(),
  intent_xid xid8 NOT NULL DEFAULT pg_current_xact_id(),
  answer text NULL CHECK (answer IN ('started', 'already_started', 'collision', 'refused', 'throttled',
                                     'not_permitted', 'check_unavailable')),
  run_id text NULL,
  answered_at timestamptz NULL,
  PRIMARY KEY (request_id, attempt),
  CONSTRAINT start_sends_answered CHECK ((answer IS NULL) = (answered_at IS NULL)),
  CONSTRAINT start_sends_run CHECK ((answer IS NOT DISTINCT FROM 'started') = (run_id IS NOT NULL)))""",
]
GRANTS = [
    "GRANT SELECT, INSERT, UPDATE, DELETE ON unresolved_sends TO dewpoint_dispatch",
    "GRANT SELECT, INSERT, UPDATE ON start_sends TO dewpoint_dispatch",
    "GRANT SELECT, UPDATE, DELETE ON unresolved_sends, start_sends TO dewpoint_retention",
]
FENCE = [
    """CREATE FUNCTION run_requests_send_recorded() RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp
AS $$
BEGIN
  -- the dispatcher's own hold (`Held`): back to `starting` with nothing sent, said in its transaction
  IF NEW.sends = OLD.sends AND current_setting('dewpoint.start_held', true) = 'on' THEN
    RETURN NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM start_sends s WHERE s.request_id = NEW.id AND s.attempt = NEW.sends
                 AND s.intent_xid = pg_current_xact_id()) THEN
    RAISE EXCEPTION 'run_requests_send_recorded: a start send is counted only with its intent recorded in the same '
                    'transaction' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NULL;
END $$""",
    "CREATE CONSTRAINT TRIGGER run_requests_send_recorded AFTER UPDATE ON run_requests DEFERRABLE INITIALLY DEFERRED "
    "FOR EACH ROW WHEN (NEW.status = 'starting' AND (OLD.status IS DISTINCT FROM NEW.status "
    "OR OLD.sends IS DISTINCT FROM NEW.sends)) EXECUTE FUNCTION run_requests_send_recorded()",
]
BACKFILL = [
    f"""DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM execution_evidence WHERE run_id IS NULL AND unproven
             AND workflow_id !~ '^t:{UUID}:run:{UUID}$') THEN
    RAISE EXCEPTION '0054 refused: an unproven root execution names no request: its attempt can''t be blocked';
  END IF;
END $$""",
    """INSERT INTO unresolved_sends (request_id, tenant_id, workflow_id, start_request_id, legacy_unknown, state)
SELECT r.id, r.tenant_id, 't:' || r.tenant_id || ':run:' || r.id, r.start_request_id, true, 'unresolved'
  FROM run_requests r WHERE r.status = 'starting'
ON CONFLICT (request_id) DO NOTHING""",
    """INSERT INTO unresolved_sends (request_id, tenant_id, workflow_id, start_request_id, legacy_unknown, state)
SELECT split_part(e.workflow_id, ':', 4)::uuid, e.tenant_id, e.workflow_id, r.start_request_id, true, 'unresolved'
  FROM execution_evidence e LEFT JOIN run_requests r ON r.id = split_part(e.workflow_id, ':', 4)::uuid
 WHERE e.run_id IS NULL AND e.unproven
ON CONFLICT (request_id) DO NOTHING""",
]
REFUSE_DOWNGRADE = """DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM unresolved_sends) THEN
    RAISE EXCEPTION '0054 refused: a blocker is left, a send that may still create an execution: never dropped';
  END IF;
END $$"""


def upgrade() -> None:
    for statement in (LOCK_TIMEOUT, *TABLES, *GRANTS, *FENCE, *BACKFILL):
        op.execute(statement)


# Taken before the refusal checks, so a blocker committed while the downgrade waits is seen, never dropped (the owner's
# third gate-B review), in the order a start writes them; a settlement answering its send first that deadlocks with it
# is rolled back, or the downgrade is: either way nothing is dropped
LOCKED = "LOCK TABLE run_requests, unresolved_sends, start_sends IN ACCESS EXCLUSIVE MODE"


def downgrade() -> None:
    for statement in (LOCK_TIMEOUT, LOCKED, REFUSE_DOWNGRADE):
        op.execute(statement)
    op.execute("DROP TRIGGER run_requests_send_recorded ON run_requests")
    op.execute("DROP FUNCTION run_requests_send_recorded()")
    op.execute("DROP TABLE start_sends")
    op.execute("DROP TABLE unresolved_sends")
