# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4, the start-check slice: the database's start check, which D12's authorizer asks before it lets a root run
start on the engine queue (the upgrade barrier's revisions 16 and 17; the owner's go, 2026-10-10). A provisional slot,
on the lineage-reconciliation list with 0049 to 0051.

`run_requests` records what each start carries, and how many were sent:
- `start_request_id`: set once, by a request's first send's intent, and sent as the request id of every start of it.
  Temporal keeps a start's request id with its started event, so the execution is identified without a key;
- `sends`: counted by each send's intent, before the send (one SDK RPC attempt each, at most 10);
- `unavailable_sends`: the sends D12 denied because its check couldn't be made, so a request whose sends are spent
  ends with a reason that says so (infrastructure, never a refusal);
- `not_permitted_sends`: the sends D12 denied as not permitted, so an end they led to is alerted as an integrity
  failure, whatever else its last send got (revision 17, section 2).

`start_permitted(workflow_id, request_id)` is true only for an eligible dispatcher request, matched by both ids: the
workflow id exactly a root run's (`t:<tenant>:run:<request>`, both canonical lower-case UUIDs), the request id
canonical too; the request `starting`, not cancelled or ended, within the cap; its recorded start request id equal;
its root evidence written; its tenant not fenced. False for anything else, never an error: the canonical forms are
checked before any cast (PL/pgSQL: an `AND` in SQL orders nothing). VOLATILE: each query in a volatile function takes
a fresh snapshot, where a STABLE one reads its calling statement's (PostgreSQL 16, "Function Volatility Categories"),
so a check whose statement began before a cancel committed still sees it.

`dewpoint_start_check`: the authorizer's role, NOLOGIN, granted EXECUTE on the function and nothing else; a
deployment grants LOGIN to a member. Adding a nullable column, defaulted ones and a function: no table rewrite, no
long lock (D15).

The rollout order (the owner's ruling, 2026-10-10): this migration, then every dispatcher on a build that records and
sends the start request id, and only then D12's start check turned on (DEWPOINT_AUTHZ_START_CHECK=on). Before 0052 a
request has no recorded id and no counted send, so the check refuses every start of it; and a dispatcher from before
this slice reads that denial as a certain refusal, ending the request dead after ten."""

from alembic import op

from migrations.online import exists, grants, online, step, ungranted

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # str(uuid.UUID): canonical, lower case
CAP = 10  # a request's start sends, at most (the owner's ruling on revision 12)
SIGNATURE = "start_permitted(text, text)"
COLUMNS = (
    "ADD COLUMN start_request_id uuid, ADD COLUMN sends integer NOT NULL DEFAULT 0, "
    "ADD COLUMN unavailable_sends integer NOT NULL DEFAULT 0, ADD COLUMN not_permitted_sends integer NOT NULL DEFAULT 0"
)
ROLE = [
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dewpoint_start_check') "
    "THEN CREATE ROLE dewpoint_start_check NOLOGIN; END IF; END $$",
]
CHECK = [
    f"""CREATE FUNCTION start_permitted(p_workflow_id text, p_request_id text) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    ids text[];
BEGIN
    ids := regexp_match(p_workflow_id, '^t:({UUID}):run:({UUID})$');
    IF ids IS NULL OR p_request_id IS NULL OR p_request_id !~ '^{UUID}$' THEN
        RETURN false;
    END IF;
    RETURN EXISTS (
        SELECT 1 FROM run_requests q
        WHERE q.id = ids[2]::uuid AND q.tenant_id = ids[1]::uuid
          AND q.status = 'starting' AND q.cancel_requested_at IS NULL AND q.ended_at IS NULL
          AND q.sends BETWEEN 1 AND {CAP}
          AND q.start_request_id = p_request_id::uuid
          AND EXISTS (SELECT 1 FROM execution_evidence e
                      WHERE e.tenant_id = q.tenant_id AND e.workflow_id = p_workflow_id AND e.run_id IS NULL)
          AND NOT EXISTS (SELECT 1 FROM tenant_erasures f
                          WHERE f.tenant_id = q.tenant_id AND f.fenced_at IS NOT NULL));
END $$""",
    f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC",
    f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO dewpoint_start_check",
]
UNROLE = [
    f"REVOKE EXECUTE ON FUNCTION {SIGNATURE} FROM dewpoint_start_check",
    "DROP ROLE IF EXISTS dewpoint_start_check",
]


def upgrade() -> None:
    with online() as conn:
        step(conn, "0052 a request's start id and sends", f"ALTER TABLE run_requests {COLUMNS}",
             done=exists("column", "not_permitted_sends", "run_requests"))  # fmt: skip
        step(conn, "0052 the start check's role", *ROLE)
        step(conn, "0052 start_permitted", *ungranted(*CHECK), done=exists("function", SIGNATURE))
        step(conn, "0052 grants", *grants(*CHECK))


def downgrade() -> None:
    for statement in UNROLE:
        op.execute(statement)
    op.execute(f"DROP FUNCTION {SIGNATURE}")
    op.execute(
        "ALTER TABLE run_requests DROP COLUMN not_permitted_sends, DROP COLUMN unavailable_sends, DROP COLUMN sends, "
        "DROP COLUMN start_request_id"
    )
