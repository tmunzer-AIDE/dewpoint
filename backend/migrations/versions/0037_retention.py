# SPDX-License-Identifier: Apache-2.0
"""Retention (engine 2b spec §10.1, §10.3): a tenant's retention, `tenant_retention.runs_days`, 30 unless its admins
set it (`tenant.manage`) within the platform's bounds, 1 to 365; no row means the default.

A run tree's data is due after its root ended, so every run records its root, `runs.root_run_id`: a root run is its
own, a sub-run its parent's. The database sets it on insert, whatever the writer gives, and refuses any change to a
run's root or parent; existing runs are backfilled from their trees.

The retention job's role, `dewpoint_retention` (§10.3): `DELETE` on the retained tables, which no other role has (a
run's steps go with it), under each tenant's scope; the reads it needs; the retained counters of the endpoints and
the tenants whose events it deletes; every tenant's id and status, to sweep each in turn. Each sweep is recorded in
`retention_sweeps`, which the dispatcher reads for the SLO's check, with its counts per tenant in
`retention_sweep_tenants`."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql as pg

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
UNROLE = [  # after retention_sweeps is dropped, with its sequence and their grants
    "REVOKE EXECUTE ON FUNCTION audit_append(uuid, uuid, text, text, text, jsonb) FROM dewpoint_retention",
    *(f"DROP POLICY {t}_retention ON {t}" for t in SCOPED),
    "DROP POLICY tenants_retention ON tenants",
    f"REVOKE ALL ON {', '.join(RETAINED)}, tenants, tenant_retention, webhook_endpoints, tenant_event_counters "
    "FROM dewpoint_retention",
    "REVOKE ALL ON SCHEMA public FROM dewpoint_retention",
    "DROP ROLE IF EXISTS dewpoint_retention",
]
BACKFILL = """WITH RECURSIVE tree AS (
  SELECT id, id AS root FROM runs WHERE parent_run_id IS NULL
  UNION ALL
  SELECT r.id, t.root FROM runs r JOIN tree t ON r.parent_run_id = t.id
)
UPDATE runs SET root_run_id = tree.root FROM tree WHERE runs.id = tree.id"""


def upgrade() -> None:
    op.create_table(
        "tenant_retention",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("runs_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("updated_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("runs_days BETWEEN 1 AND 365", name="tenant_retention_bounds"),
    )
    for statement in (
        "ALTER TABLE tenant_retention ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE tenant_retention FORCE ROW LEVEL SECURITY",
        "CREATE POLICY tenant_retention_scope ON tenant_retention TO dewpoint_api, dewpoint_dispatch "
        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        "GRANT SELECT, INSERT ON tenant_retention TO dewpoint_api",
        "GRANT SELECT ON tenant_retention TO dewpoint_dispatch",  # the dev CLI's retry, under its cutoff
        "GRANT UPDATE (runs_days, updated_by, updated_at) ON tenant_retention TO dewpoint_api",
    ):
        op.execute(statement)
    op.add_column("runs", sa.Column("root_run_id", pg.UUID(as_uuid=True), nullable=True))
    conn = op.get_bind()
    conn.execute(text("SET LOCAL row_security = off"))  # every tenant's runs: a role RLS applies to errors here
    conn.execute(text(BACKFILL))
    conn.execute(text("SET LOCAL row_security TO DEFAULT"))
    op.alter_column("runs", "root_run_id", nullable=False)
    op.create_foreign_key("runs_root_run", "runs", "runs", ["root_run_id", "tenant_id"], ["id", "tenant_id"])
    op.create_index("runs_tree", "runs", ["tenant_id", "root_run_id"])
    for statement in ROOTS:
        op.execute(statement)
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
    for statement in ROLE:
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("retention_sweep_tenants")
    op.drop_table("retention_sweeps")
    for statement in UNROLE:
        op.execute(statement)
    op.execute("DROP TRIGGER runs_tree ON runs")
    op.execute("DROP FUNCTION runs_tree_fixed()")
    op.execute("DROP TRIGGER runs_root ON runs")
    op.execute("DROP FUNCTION runs_set_root()")
    op.drop_index("runs_tree", "runs")
    op.drop_constraint("runs_root_run", "runs", type_="foreignkey")
    op.drop_column("runs", "root_run_id")
    op.drop_table("tenant_retention")
