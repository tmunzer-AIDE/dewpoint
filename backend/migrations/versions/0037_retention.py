# SPDX-License-Identifier: Apache-2.0
"""Retention (engine 2b spec §10.1, §10.3): a tenant's retention, `tenant_retention.runs_days`, 30 unless its admins
set it (`tenant.manage`) within the platform's bounds, 1 to 365; no row means the default.

A run tree's data is due after its root ended, so every run records its root, `runs.root_run_id`: a root run is its
own, a sub-run its parent's. The database sets it on insert, whatever the writer gives, and refuses any change to a
run's root or parent; existing runs are backfilled from their trees. A sub-run its root's end left `running` holds
its tree: the reconciler describes its own execution, at most once a recheck (`runs.checked_at`), through
`orphan_subruns()`, ids only (the final review's M5).

The retention job's role, `dewpoint_retention` (§10.3): `DELETE` on the retained tables, which no other role has (a
run's steps go with it), under each tenant's scope; the reads it needs; the retained counters of the endpoints and
the tenants whose events it deletes; every tenant's id and status, to sweep each in turn. Each sweep is recorded in
`retention_sweeps`, which the dispatcher reads for the SLO's check, with its counts per tenant in
`retention_sweep_tenants`."""

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from migrations.online import batches, exists, index, online, plain, step

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

ROOTS = [
    """CREATE FUNCTION runs_set_root() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.parent_run_id IS NULL THEN
    NEW.root_run_id := NEW.id;
  ELSE
    SELECT root_run_id INTO NEW.root_run_id FROM runs WHERE id = NEW.parent_run_id AND tenant_id = NEW.tenant_id;
    -- a parent that isn't a run of the tenant: the parent's key refuses the row, a foreign-key violation
    NEW.root_run_id := COALESCE(NEW.root_run_id, NEW.parent_run_id);
  END IF;
  RETURN NEW;
END $$""",
    "CREATE TRIGGER runs_root BEFORE INSERT ON runs FOR EACH ROW EXECUTE FUNCTION runs_set_root()",
    """CREATE FUNCTION runs_tree_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.root_run_id IS DISTINCT FROM OLD.root_run_id OR NEW.parent_run_id IS DISTINCT FROM OLD.parent_run_id THEN
    RAISE EXCEPTION 'a run''s tree never changes';
  END IF;
  RETURN NEW;
END $$""",
    "CREATE TRIGGER runs_tree BEFORE UPDATE OF root_run_id, parent_run_id ON runs FOR EACH ROW "
    "EXECUTE FUNCTION runs_tree_fixed()",
]
ORPHANS = [
    """CREATE FUNCTION orphan_subruns(grace interval, recheck interval, max_rows integer)
RETURNS TABLE (tenant_id uuid, run_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT c.tenant_id, c.id FROM runs c JOIN runs r ON r.id = c.root_run_id AND r.tenant_id = c.tenant_id
  WHERE c.status = 'running' AND c.parent_run_id IS NOT NULL AND r.status <> 'running'
    AND r.ended_at < statement_timestamp() - grace
    AND (c.checked_at IS NULL OR c.checked_at < statement_timestamp() - recheck)
  ORDER BY c.checked_at NULLS FIRST, r.ended_at, c.id
  LIMIT max_rows
$$""",
    "REVOKE ALL ON FUNCTION orphan_subruns(interval, interval, integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION orphan_subruns(interval, interval, integer) TO dewpoint_dispatch",
]
COUNTED = ("runs", "requests", "events", "csv_uploads", "schedules")  # what a sweep deletes, per tenant
RETAINED = ("runs", "step_outputs", "run_inputs", "run_secret_index", "claim_grants", "run_requests", "inbound_events",
            "csv_uploads", "schedules")  # fmt: skip
SCOPED = ("run_requests", "inbound_events", "csv_uploads", "schedules", "webhook_endpoints", "tenant_event_counters",
          "tenant_retention")  # their policies name their roles: the others' apply to every role  # fmt: skip
ROLE = [
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dewpoint_retention') "
    "THEN CREATE ROLE dewpoint_retention NOLOGIN; END IF; END $$",
    "GRANT USAGE ON SCHEMA public TO dewpoint_retention",
    f"GRANT SELECT, DELETE ON {', '.join(RETAINED)} TO dewpoint_retention",
    "GRANT SELECT (id, status) ON tenants TO dewpoint_retention",
    "CREATE POLICY tenants_retention ON tenants FOR SELECT TO dewpoint_retention USING (true)",
    "GRANT SELECT ON tenant_retention TO dewpoint_retention",
    "GRANT SELECT (id, tenant_id, retained_events, retained_bytes) ON webhook_endpoints TO dewpoint_retention",
    "GRANT SELECT (tenant_id, retained_events, retained_bytes) ON tenant_event_counters TO dewpoint_retention",
    "GRANT UPDATE (retained_events, retained_bytes) ON webhook_endpoints, tenant_event_counters TO dewpoint_retention",
    *(
        f"CREATE POLICY {t}_retention ON {t} TO dewpoint_retention USING (tenant_id = app_tenant_id()) "
        "WITH CHECK (tenant_id = app_tenant_id())"
        for t in SCOPED
    ),
    "GRANT EXECUTE ON FUNCTION audit_append(uuid, uuid, text, text, text, jsonb) TO dewpoint_retention",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON retention_sweeps TO dewpoint_retention",  # its own records, after 30 days
    "GRANT SELECT, INSERT, UPDATE ON retention_sweep_tenants TO dewpoint_retention",
    "GRANT USAGE ON SEQUENCE retention_sweeps_id_seq TO dewpoint_retention",
    "GRANT SELECT ON retention_sweeps TO dewpoint_dispatch, dewpoint_admin",
]
# A sweep's counts per tenant are that tenant's (the final review's M3): read and written in its scope. The sweep's end
# reads them across tenants through functions returning ids or a summary only. `retention_sweeps` holds no tenant's
# rows: a platform table, its grants its boundary. An old sweep's record takes its counts with it: the key's cascade
# runs as the table's owner, which the policies don't hold.
SWEEP_SCOPE = [
    "ALTER TABLE retention_sweep_tenants ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE retention_sweep_tenants FORCE ROW LEVEL SECURITY",
    "CREATE POLICY retention_sweep_tenants_scope ON retention_sweep_tenants TO dewpoint_retention "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    """CREATE FUNCTION retention_sweep_unaudited(p_sweep bigint) RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp AS $$
  SELECT tenant_id FROM retention_sweep_tenants WHERE sweep_id = p_sweep AND audited_at IS NULL ORDER BY tenant_id
$$""",
    """CREATE FUNCTION retention_sweep_summary(p_sweep bigint, OUT tenants bigint, OUT unaudited bigint,
  OUT failed boolean, OUT lag_s double precision) LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp AS $$
  SELECT count(*) FILTER (WHERE audited_at IS NOT NULL), count(*) FILTER (WHERE audited_at IS NULL),
         coalesce(bool_or(failed), false), coalesce(max(lag_s), 0)
  FROM retention_sweep_tenants WHERE sweep_id = p_sweep
$$""",
    "REVOKE ALL ON FUNCTION retention_sweep_unaudited(bigint), retention_sweep_summary(bigint) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION retention_sweep_unaudited(bigint), retention_sweep_summary(bigint) TO dewpoint_retention",
]
UNROLE = [  # after retention_sweeps is dropped, with its sequence and their grants
    "REVOKE EXECUTE ON FUNCTION audit_append(uuid, uuid, text, text, text, jsonb) FROM dewpoint_retention",
    *(f"DROP POLICY {t}_retention ON {t}" for t in SCOPED),
    "DROP POLICY tenants_retention ON tenants",
    f"REVOKE ALL ON {', '.join(RETAINED)}, tenants, tenant_retention, webhook_endpoints, tenant_event_counters "
    "FROM dewpoint_retention",
    "REVOKE ALL ON SCHEMA public FROM dewpoint_retention",
    "DROP ROLE IF EXISTS dewpoint_retention",
]
# Online (2b-4b, D15): existing runs backfilled in committed batches, each run walked up to the first ancestor with its
# root (or to its root), while new runs get theirs from the trigger, which walks a parent not backfilled yet the same way;
# its original body is restored once every run has its root.
WALKING = """CREATE OR REPLACE FUNCTION runs_set_root() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.parent_run_id IS NULL THEN
    NEW.root_run_id := NEW.id;
  ELSE
    NEW.root_run_id := (WITH RECURSIVE up (id, parent, root, depth) AS (
      SELECT id, parent_run_id, root_run_id, 0 FROM runs WHERE id = NEW.parent_run_id AND tenant_id = NEW.tenant_id
      UNION ALL
      SELECT r.id, r.parent_run_id, r.root_run_id, up.depth + 1 FROM runs r JOIN up ON r.id = up.parent
      WHERE up.root IS NULL AND up.depth < 1000
    ) SELECT coalesce(root, id) FROM up WHERE root IS NOT NULL OR parent IS NULL LIMIT 1);
    NEW.root_run_id := COALESCE(NEW.root_run_id, NEW.parent_run_id);
  END IF;
  RETURN NEW;
END $$"""
BACKFILL_BOUNDS = (  # the batch's last id (uuid has no max()) and its size
    "WITH b AS (SELECT id FROM runs WHERE root_run_id IS NULL AND id > :after ORDER BY id LIMIT :n) "
    "SELECT (SELECT id FROM b ORDER BY id DESC LIMIT 1), (SELECT count(*) FROM b)"
)
BACKFILL = """WITH RECURSIVE up (id, at, parent, root, depth) AS (
  SELECT id, id, parent_run_id, root_run_id, 0 FROM runs WHERE root_run_id IS NULL AND id > :after AND id <= :hi
  UNION ALL
  SELECT up.id, r.id, r.parent_run_id, r.root_run_id, up.depth + 1 FROM up JOIN runs r ON r.id = up.parent
  WHERE up.root IS NULL AND up.parent IS NOT NULL AND up.depth < 1000
)
UPDATE runs SET root_run_id = coalesce(up.root, up.at) FROM up
WHERE runs.id = up.id AND (up.root IS NOT NULL OR up.parent IS NULL)"""
CHECKED = "runs_root_run_id_not_null"  # NOT NULL through a validated check: setting it then reads no row
NOT_NULL = "SELECT attnotnull FROM pg_attribute WHERE attrelid = 'public.runs'::regclass AND attname = 'root_run_id'"
TENANT_RETENTION = [
    "ALTER TABLE tenant_retention ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE tenant_retention FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_retention_scope ON tenant_retention TO dewpoint_api, dewpoint_dispatch "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "GRANT SELECT, INSERT ON tenant_retention TO dewpoint_api",
    "GRANT SELECT ON tenant_retention TO dewpoint_dispatch",  # the dev CLI's retry, under its cutoff
    "GRANT UPDATE (runs_days, updated_by, updated_at) ON tenant_retention TO dewpoint_api",
]


def upgrade() -> None:
    # Online (2b-4b, D15), in the original's order: each step's catalogue changes in one transaction; the backfill in
    # batches; `NOT NULL` through a check validated first; the key added `NOT VALID`, then validated; the indexes built
    # concurrently. None of these blocks normal reads or writes for longer than a step.
    with online() as conn:
        step(conn, "0037 tenant_retention", _tenant_retention, *TENANT_RETENTION,
             done=exists("relation", "tenant_retention"))  # fmt: skip
        step(conn, "0037 runs.root_run_id",
             lambda: op.add_column("runs", sa.Column("root_run_id", pg.UUID(as_uuid=True), nullable=True)),
             WALKING, ROOTS[1], done=exists("column", "root_run_id", "runs"))  # fmt: skip
        batches(conn, "0037 runs.root_run_id backfill", BACKFILL_BOUNDS, BACKFILL, first=UUID(int=0))
        step(conn, "0037 runs.root_run_id checked",
             f"ALTER TABLE runs ADD CONSTRAINT {CHECKED} CHECK (root_run_id IS NOT NULL) NOT VALID",
             done=f"SELECT ({NOT_NULL}) OR ({exists('constraint', CHECKED)})")  # fmt: skip
        plain(conn, "0037 runs.root_run_id validated", f"ALTER TABLE runs VALIDATE CONSTRAINT {CHECKED}", done=NOT_NULL)
        step(conn, "0037 runs.root_run_id not null", "ALTER TABLE runs ALTER COLUMN root_run_id SET NOT NULL",
             f"ALTER TABLE runs DROP CONSTRAINT {CHECKED}", done=NOT_NULL)  # fmt: skip
        step(conn, "0037 runs_root_run",
             "ALTER TABLE runs ADD CONSTRAINT runs_root_run FOREIGN KEY (root_run_id, tenant_id) "
             "REFERENCES runs (id, tenant_id) NOT VALID", done=exists("constraint", "runs_root_run"))  # fmt: skip
        plain(conn, "0037 runs_root_run validated", "ALTER TABLE runs VALIDATE CONSTRAINT runs_root_run")
        index(
            conn, "0037 runs_tree", "CREATE INDEX CONCURRENTLY IF NOT EXISTS runs_tree ON runs (tenant_id, root_run_id)"
        )
        step(conn, "0037 the runs' tree", ROOTS[0].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1),
             *ROOTS[2:], lambda: op.add_column("runs", sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True)),
             done=exists("trigger", "runs_tree", "runs"))  # fmt: skip
        index(conn, "0037 runs_open_subruns",
              "CREATE INDEX CONCURRENTLY IF NOT EXISTS runs_open_subruns ON runs (checked_at, id) "
              "WHERE status = 'running' AND parent_run_id IS NOT NULL")  # fmt: skip
        # The retention role, then its policies, a step a table (a step locks at most one table in use; a policy
        # naming a role with no grant opens nothing), then its grants with the sweeps' tables, which lock none.
        step(conn, "0037 the retention role", *ROLE[:2], done=exists("policy", "tenants_retention", "tenants"))
        for statement in (s for s in ROLE if s.startswith("CREATE POLICY")):
            table = statement.split(" ON ", 1)[1].split()[0]
            step(conn, f"0037 {table} for retention", statement,
                 done=exists("policy", statement.split()[2], table))  # fmt: skip
        step(conn, "0037 retention", *ORPHANS, _retention_sweeps, _retention_sweep_tenants,
             *(s for s in ROLE[2:] if not s.startswith("CREATE POLICY")), *SWEEP_SCOPE,
             done=exists("relation", "retention_sweeps"))  # fmt: skip


def _tenant_retention() -> None:
    op.create_table(
        "tenant_retention",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("runs_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("updated_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("runs_days BETWEEN 1 AND 365", name="tenant_retention_bounds"),
    )


def _retention_sweeps() -> None:
    op.create_table(
        "retention_sweeps",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("succeeded", sa.Boolean),
        sa.Column("tenants", sa.Integer),  # how many it swept
        sa.Column("lag_s", sa.Float),  # how far past its cutoff the oldest data still stored is, at its end
        sa.CheckConstraint("(ended_at IS NULL) = (succeeded IS NULL)", name="retention_sweeps_ended"),
    )


def _retention_sweep_tenants() -> None:
    op.create_table(  # a sweep's counts per tenant, kept by the batches that deleted, and whether its entry is written
        "retention_sweep_tenants",
        sa.Column(
            "sweep_id", sa.BigInteger, sa.ForeignKey("retention_sweeps.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), primary_key=True),
        *(sa.Column(kind, sa.BigInteger, nullable=False, server_default="0") for kind in COUNTED),
        sa.Column("lag_s", sa.Float),
        sa.Column("failed", sa.Boolean, nullable=False, server_default=sa.false()),  # its sweep failed: kept, so a
        sa.Column("audited_at", sa.DateTime(timezone=True)),  # resumed sweep still ends unsuccessful
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION retention_sweep_summary(bigint)")
    op.execute("DROP FUNCTION retention_sweep_unaudited(bigint)")
    op.drop_table("retention_sweep_tenants")
    op.drop_table("retention_sweeps")
    for statement in UNROLE:
        op.execute(statement)
    op.execute("DROP FUNCTION orphan_subruns(interval, interval, integer)")
    op.drop_index("runs_open_subruns", "runs")
    op.drop_column("runs", "checked_at")
    op.execute("DROP TRIGGER runs_tree ON runs")
    op.execute("DROP FUNCTION runs_tree_fixed()")
    op.execute("DROP TRIGGER runs_root ON runs")
    op.execute("DROP FUNCTION runs_set_root()")
    op.drop_index("runs_tree", "runs")
    op.drop_constraint("runs_root_run", "runs", type_="foreignkey")
    op.drop_column("runs", "root_run_id")
    op.drop_table("tenant_retention")
