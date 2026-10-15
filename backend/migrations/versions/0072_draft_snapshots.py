# SPDX-License-Identifier: Apache-2.0
"""B8 (editor 4d-1b; the simulation design §6.1): draft snapshots, and requests and runs frozen on one.

- `draft_snapshots`: what a version row carries, frozen from a workflow's draft for a simulation (its graph and
  references, engine ABI and CEL profile, pins and closure, schemas, CEL records, taint, declassified sites, caps and
  hashes), with the draft's revision and who first froze it. One per workflow and `version_hash` (which covers the ABI
  and the CEL profile), so identical drafts share one. Immutable: an UPDATE is refused; only the retention role
  deletes (an unreferenced snapshot past its runs, §6.2; a tenant's erasure). Nothing points at it from `workflows`, so
  no trigger can start one.
- `run_requests` and `runs`: `draft_snapshot_id` (its key with the workflow and tenant), exactly one of it or
  `workflow_version_id` (a refused request may have neither), a snapshot only in `simulate`, a `target_step_id` only
  with a snapshot. A request also records the draft revision it was admitted at and the checks it reported.
- Indexes: each table's snapshot (the foreign keys' checks, the sweep's), a person's draft requests of a workflow
  (their latest simulations), and the published runs' `runs_workflow_last` (the workflows list's last runs, which leave
  draft runs out; the old index stays while the old code reads it).

Online (2b-4b, D15): a step locks at most one table in use; the checks go in `NOT VALID` and are validated outside a
transaction; the indexes are built concurrently; the grants come last. Its downgrade refuses while a snapshot is kept,
its locks taken before it checks.

Slot 0072 is the ledger's (B8), chained after 0071."""

from alembic import op

from migrations.online import exists, grants, index, online, plain, step, ungranted

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None

TABLE = """CREATE TABLE draft_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants (id),
  workflow_id uuid NOT NULL,
  draft_revision integer NOT NULL,
  graph jsonb NOT NULL,
  node_refs text[] NOT NULL,
  engine_abi integer NOT NULL,
  cel_profile varchar(120) NOT NULL REFERENCES cel_profiles (profile),
  connection_ids uuid[] NOT NULL DEFAULT '{}',
  subflow_version_ids jsonb NOT NULL DEFAULT '{}'::jsonb,
  failure_handler_version_id uuid NULL,
  input_schema jsonb NOT NULL,
  output_schema jsonb NOT NULL,
  vars_schema jsonb NOT NULL,
  expressions jsonb NOT NULL DEFAULT '[]'::jsonb,
  tainted_sites jsonb NOT NULL DEFAULT '[]'::jsonb,
  output_taint jsonb NULL,
  declassified jsonb NOT NULL DEFAULT '[]'::jsonb,
  open_scopes_cap integer NULL,
  loop_depth integer NULL,
  closure_version_ids uuid[] NOT NULL,
  closure_workflow_ids uuid[] NOT NULL,
  closure_node_refs text[] NOT NULL,
  closure_cel_profiles text[] NOT NULL,
  closure_depth integer NOT NULL,
  graph_hash varchar(64) NOT NULL,
  version_hash varchar(64) NOT NULL,
  created_by uuid NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT draft_snapshots_hash UNIQUE (workflow_id, version_hash),
  CONSTRAINT draft_snapshots_tenant UNIQUE (id, workflow_id, tenant_id),
  CONSTRAINT draft_snapshots_workflow FOREIGN KEY (workflow_id, tenant_id) REFERENCES workflows (id, tenant_id))"""
IMMUTABLE = """CREATE FUNCTION draft_snapshots_immutable() RETURNS trigger LANGUAGE plpgsql
SET search_path = public, pg_temp AS $$
BEGIN
  RAISE EXCEPTION 'draft_snapshots rows are immutable';
END $$"""
SNAPSHOTS = (
    TABLE,
    "ALTER TABLE draft_snapshots ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE draft_snapshots FORCE ROW LEVEL SECURITY",
    "CREATE POLICY draft_snapshots_scope ON draft_snapshots "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "CREATE POLICY draft_snapshots_platform_read ON draft_snapshots FOR SELECT TO dewpoint_admin USING (true)",
    IMMUTABLE,
    "REVOKE ALL ON FUNCTION draft_snapshots_immutable() FROM PUBLIC",
    "CREATE TRIGGER draft_snapshots_immutable BEFORE UPDATE ON draft_snapshots FOR EACH ROW "
    "EXECUTE FUNCTION draft_snapshots_immutable()",
    "CREATE TRIGGER draft_snapshots_fence BEFORE INSERT ON draft_snapshots FOR EACH ROW "
    "EXECUTE FUNCTION tenant_insert_fence()",
    "GRANT SELECT, INSERT ON draft_snapshots TO dewpoint_api",
    "GRANT SELECT ON draft_snapshots TO dewpoint_dispatch, dewpoint_worker, dewpoint_admin",
    "GRANT SELECT, DELETE ON draft_snapshots TO dewpoint_retention",
)
REQUEST_SHAPE = ("(draft_snapshot_id IS NULL AND target_step_id IS NULL AND draft_revision IS NULL "
                 "AND admission_checks IS NULL) OR (draft_snapshot_id IS NOT NULL AND mode = 'simulate' "
                 "AND draft_revision IS NOT NULL)")  # fmt: skip
FROZEN = ("num_nonnulls(workflow_version_id, draft_snapshot_id) <= 1 "
          "AND (status = 'refused' OR num_nonnulls(workflow_version_id, draft_snapshot_id) = 1)")  # fmt: skip
WIDER = "run_requests_frozen_0072"
WIDENED = ("SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'run_requests_frozen' "
           "AND pg_get_constraintdef(oid) LIKE '%draft_snapshot_id%')")  # fmt: skip
REQUESTS = {  # each check, added NOT VALID, then validated
    "run_requests_draft": "FOREIGN KEY (draft_snapshot_id, workflow_id, tenant_id) "
    "REFERENCES draft_snapshots (id, workflow_id, tenant_id)",
    "run_requests_draft_shape": f"CHECK ({REQUEST_SHAPE})",
    WIDER: f"CHECK ({FROZEN})",
}
RUN_SHAPE = ("(draft_snapshot_id IS NULL AND target_step_id IS NULL) "
             "OR (draft_snapshot_id IS NOT NULL AND mode = 'simulate')")  # fmt: skip
RUNS = {
    "runs_draft_fk": "FOREIGN KEY (draft_snapshot_id, workflow_id, tenant_id) "
    "REFERENCES draft_snapshots (id, workflow_id, tenant_id)",
    "runs_draft_shape": f"CHECK ({RUN_SHAPE})",
    "runs_frozen": "CHECK (num_nonnulls(workflow_version_id, draft_snapshot_id) = 1)",
}
INDEXES = {
    "run_requests_draft_snapshot": "ON run_requests (draft_snapshot_id) WHERE draft_snapshot_id IS NOT NULL",
    "runs_draft_snapshot": "ON runs (draft_snapshot_id) WHERE draft_snapshot_id IS NOT NULL",
    "run_requests_drafts": "ON run_requests (tenant_id, workflow_id, actor_id, queued_at DESC, id DESC) "
    "WHERE draft_snapshot_id IS NOT NULL",
    "runs_workflow_last_published": "ON runs (workflow_id, mode, queued_at DESC, id DESC) "
    "WHERE kind = 'run' AND draft_snapshot_id IS NULL",
}
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
LOCKED = "LOCK TABLE draft_snapshots, run_requests, runs IN ACCESS EXCLUSIVE MODE"
REFUSE_DOWNGRADE = """DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM draft_snapshots) THEN
    RAISE EXCEPTION '0072 refused: a draft snapshot is kept';
  END IF;
END $$"""


def upgrade() -> None:
    with online() as conn:
        step(conn, "0072 draft_snapshots", *ungranted(*SNAPSHOTS), done=exists("relation", "draft_snapshots"))
        step(conn, "0072 run_requests columns",
             "ALTER TABLE run_requests ADD COLUMN draft_snapshot_id uuid, ADD COLUMN target_step_id uuid, "
             "ADD COLUMN draft_revision integer, ADD COLUMN admission_checks jsonb",
             done=exists("column", "draft_snapshot_id", "run_requests"))  # fmt: skip
        step(conn, "0072 run_requests checks",
             *(f"ALTER TABLE run_requests ADD CONSTRAINT {name} {check} NOT VALID" for name, check in REQUESTS.items()),
             done=exists("constraint", "run_requests_draft"))  # fmt: skip
        for name in REQUESTS:
            done = WIDENED if name == WIDER else f"SELECT convalidated FROM pg_constraint WHERE conname = '{name}'"
            plain(conn, f"0072 {name} validated", f"ALTER TABLE run_requests VALIDATE CONSTRAINT {name}", done=done)
        step(conn, "0072 run_requests_frozen, swapped", "ALTER TABLE run_requests DROP CONSTRAINT run_requests_frozen",
             f"ALTER TABLE run_requests RENAME CONSTRAINT {WIDER} TO run_requests_frozen", done=WIDENED)  # fmt: skip
        step(conn, "0072 runs columns",
             "ALTER TABLE runs ADD COLUMN draft_snapshot_id uuid, ADD COLUMN target_step_id uuid, "
             "ALTER COLUMN workflow_version_id DROP NOT NULL",
             done=exists("column", "draft_snapshot_id", "runs"))  # fmt: skip
        step(conn, "0072 runs checks",
             *(f"ALTER TABLE runs ADD CONSTRAINT {name} {check} NOT VALID" for name, check in RUNS.items()),
             done=exists("constraint", "runs_draft_fk"))  # fmt: skip
        for name in RUNS:
            plain(conn, f"0072 {name} validated", f"ALTER TABLE runs VALIDATE CONSTRAINT {name}",
                  done=f"SELECT convalidated FROM pg_constraint WHERE conname = '{name}'")  # fmt: skip
        for name, definition in INDEXES.items():
            index(conn, f"0072 {name}", f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} {definition}")
        step(conn, "0072 grants", *grants(*SNAPSHOTS))


def downgrade() -> None:
    for statement in (LOCK_TIMEOUT, LOCKED, REFUSE_DOWNGRADE):
        op.execute(statement)
    for name in INDEXES:
        op.execute(f"DROP INDEX {name}")
    op.execute("ALTER TABLE runs " + ", ".join(f"DROP CONSTRAINT {name}" for name in reversed(RUNS)))
    op.execute("ALTER TABLE runs DROP COLUMN target_step_id, DROP COLUMN draft_snapshot_id, "
               "ALTER COLUMN workflow_version_id SET NOT NULL")  # fmt: skip
    op.execute("ALTER TABLE run_requests DROP CONSTRAINT run_requests_frozen, DROP CONSTRAINT run_requests_draft_shape, "
               "DROP CONSTRAINT run_requests_draft")  # fmt: skip
    op.execute("ALTER TABLE run_requests ADD CONSTRAINT run_requests_frozen "
               "CHECK (status = 'refused' OR workflow_version_id IS NOT NULL)")  # fmt: skip
    op.execute("ALTER TABLE run_requests DROP COLUMN admission_checks, DROP COLUMN draft_revision, "
               "DROP COLUMN target_step_id, DROP COLUMN draft_snapshot_id")  # fmt: skip
    op.execute("DROP TABLE draft_snapshots")
    op.execute("DROP FUNCTION draft_snapshots_immutable()")
