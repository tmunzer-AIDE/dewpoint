# SPDX-License-Identifier: Apache-2.0
"""Tenant erasure (engine 2b spec §6.5; the 2b-4 outline's "Tenant erasure", D3): irreversible once `erasing` is
committed; an operator stops or retries it, never reverses it.

`tenants.status` admits `erased`: the row stays, so its id is never reused and its audit chain still resolves, as a
tombstone, never eligible again (every writer requires `active`).

`tenant_erasures`: one record per erased tenant, identifiers only, kept for good: who asked and when, the stage reached
(`step`, below), a stop, its attempts and its last failure's fixed code, the times its bound is reckoned from, the
namespace-change boundary it relied on, the sweep's counts per table, and its completion. Its stages, in order:
20 reconcile `starting` requests; 31 pause the schedules, 32 their firing inventory, 33 delete them; 40 cancel queued
requests and pending events; 50 end running runs; 60 delete every execution; 70 delete the keys; 80 the sweep; 90 the
retention bound, then the final check; 100 complete.
`tenant_erasure_items`: what a stage with an effect outside PostgreSQL works through, one row per item (a request, a
schedule, a run, an execution: its ids, where it was found), each found, then requested, then verified by a read-back.
They go when the erasure completes, its audit entry keeping their counts.
`tenant_erasure_known`: every Temporal id the erasure found (its schedules', its executions'), identifiers only, kept
after completion: the retention process describes each on every pass, for good, and a late one found reopens the
record.

`schedule_firings`: each `ScheduleTick` records its own workflow and run ids as its first act, a skip included, for the
erasure's firing inventory; identifiers only, kept 31 days (the platform's longest namespace retention, and a day).
`schedules.creation_misses`: firings due while a newly created schedule stayed paused, before its unpause (D3f): Temporal
neither catches them up nor counts them as missed, so the sync counts them.

The insert fence: once an erasure reaches stage 60 (its executions being deleted, nothing of the tenant runs any more),
no row of the tenant is inserted into any table that holds tenant data, by any role, whatever the writer: a trigger
takes the tenant's lifecycle lock, shared, and refuses the insert (SQLSTATE DPE01). Stage 60 is entered under that lock
taken exclusively, so an insert either commits before it or sees it. Not fenced: the audit log (kept under the audit
policy), and the retention sweep's own counts (deleted by the erasure's sweep once audited)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

STAGES = (20, 31, 32, 33, 40, 50, 60, 70, 80, 90, 100)
FENCED_AT = 60
# Every table holding tenant data, the keys included: what the fence covers.
FENCED = ("claim_grants", "connections", "csv_mappings", "csv_uploads", "data_keys", "egress_allowlist",
          "execution_evidence", "inbound_events", "memberships", "plugin_calls", "rate_buckets", "rate_scope_keys",
          "run_inputs", "run_requests", "run_secret_index", "run_slots", "run_steps", "runs", "schedule_firings",
          "schedules", "step_outputs", "tenant_event_counters", "tenant_event_keys", "tenant_retention",
          "tenant_run_limits", "trigger_bindings", "webhook_endpoints", "workflow_versions", "workflows")  # fmt: skip

FENCE = [
    f"""CREATE FUNCTION tenant_insert_fence() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp AS $$
BEGIN
  -- the tenant's lifecycle lock (core/ingress/counters.py), shared: entering stage {FENCED_AT} takes it exclusively
  PERFORM pg_advisory_xact_lock_shared(hashtextextended('dewpoint:tenant:' || NEW.tenant_id::text, 0));
  IF EXISTS (SELECT 1 FROM tenant_erasures e WHERE e.tenant_id = NEW.tenant_id AND e.step >= {FENCED_AT}) THEN
    RAISE EXCEPTION 'tenant_erased' USING ERRCODE = 'DPE01';
  END IF;
  RETURN NEW;
END $$""",
    "REVOKE ALL ON FUNCTION tenant_insert_fence() FROM PUBLIC",
]

FIRINGS = [
    "ALTER TABLE schedule_firings ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE schedule_firings FORCE ROW LEVEL SECURITY",
    "CREATE POLICY schedule_firings_scope ON schedule_firings TO dewpoint_dispatch, dewpoint_retention "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "GRANT SELECT, INSERT ON schedule_firings TO dewpoint_dispatch",
    "GRANT SELECT, DELETE ON schedule_firings TO dewpoint_retention",
]


def upgrade() -> None:
    op.drop_constraint("tenants_status", "tenants", type_="check")
    op.create_check_constraint("tenants_status", "tenants", "status IN ('active', 'erasing', 'erased')")
    op.create_table(
        "tenant_erasures",
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("requested_by", sa.Uuid, nullable=False),  # a platform admin's user id
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("step", sa.SmallInteger, nullable=False, server_default="20"),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_by", sa.Uuid, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failure", sa.Text, nullable=True),  # the last failure's fixed code
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),  # the last schedule verified paused
        sa.Column("latest_close", sa.DateTime(timezone=True), nullable=True),  # every found execution verified gone
        sa.Column("check_after", sa.DateTime(timezone=True), nullable=True),  # the bound: the final check's earliest
        sa.Column("boundary", sa.Text, nullable=True),  # the namespace-change boundary it relied on
        sa.Column("counts", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("incidents", sa.Integer, nullable=False, server_default="0"),
        sa.CheckConstraint(f"step IN ({', '.join(map(str, STAGES))})", name="tenant_erasures_step"),
    )
    op.create_table(
        "tenant_erasure_items",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenant_erasures.tenant_id"), nullable=False),
        sa.Column("step", sa.SmallInteger, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("workflow_id", sa.Text, nullable=False),  # a request's or run's id, a schedule's or a workflow's
        sa.Column("run_id", sa.Text, nullable=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False, server_default="found"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failure", sa.Text, nullable=True),
        sa.Column("next_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('request', 'schedule', 'run', 'execution')", name="tenant_erasure_items_kind"),
        sa.CheckConstraint("state IN ('found', 'requested', 'verified')", name="tenant_erasure_items_state"),
    )
    op.create_index("tenant_erasure_items_one", "tenant_erasure_items",
                    ["tenant_id", "step", "workflow_id", sa.text("coalesce(run_id, '')")], unique=True)  # fmt: skip
    op.create_index("tenant_erasure_items_due", "tenant_erasure_items", ["tenant_id", "step", "next_at"],
                    postgresql_where=sa.text("state <> 'verified'"))  # fmt: skip
    op.create_table(
        "tenant_erasure_known",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenant_erasures.tenant_id"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("workflow_id", sa.Text, nullable=False),  # a schedule's id, or an execution's workflow id
        sa.Column("run_id", sa.Text, nullable=True),
        sa.CheckConstraint("kind IN ('schedule', 'execution')", name="tenant_erasure_known_kind"),
    )
    op.create_index("tenant_erasure_known_one", "tenant_erasure_known",
                    ["tenant_id", "kind", "workflow_id", sa.text("coalesce(run_id, '')")], unique=True)  # fmt: skip
    op.create_table(
        "schedule_firings",
        sa.Column("workflow_id", sa.Text, primary_key=True),
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("schedule_id", sa.Uuid, nullable=False),  # no key: a tombstone goes before its firings' records
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("schedule_firings_tenant", "schedule_firings", ["tenant_id", "schedule_id"])
    op.create_index("schedule_firings_recorded", "schedule_firings", ["recorded_at"])
    for statement in FIRINGS:
        op.execute(statement)
    op.add_column("schedules", sa.Column("creation_misses", sa.Integer, nullable=False, server_default="0"))
    op.execute("GRANT UPDATE (creation_misses) ON schedules TO dewpoint_dispatch")
    for statement in FENCE:
        op.execute(statement)
    for table in FENCED:
        op.execute(f"CREATE TRIGGER {table}_fence BEFORE INSERT ON {table} FOR EACH ROW "
                   "EXECUTE FUNCTION tenant_insert_fence()")  # fmt: skip


def downgrade() -> None:
    for table in FENCED:
        op.execute(f"DROP TRIGGER {table}_fence ON {table}")
    op.execute("DROP FUNCTION tenant_insert_fence()")
    op.execute("REVOKE UPDATE (creation_misses) ON schedules FROM dewpoint_dispatch")
    op.drop_column("schedules", "creation_misses")
    op.drop_table("schedule_firings")
    op.drop_table("tenant_erasure_known")
    op.drop_table("tenant_erasure_items")
    op.drop_table("tenant_erasures")
    op.drop_constraint("tenants_status", "tenants", type_="check")
    op.create_check_constraint("tenants_status", "tenants", "status IN ('active', 'erasing')")
