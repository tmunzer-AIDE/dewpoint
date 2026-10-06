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
`schedule_incarnations` (the owner's ruling on the M4 checkpoint): every Temporal schedule id a schedule may have
been created under, each recorded and committed before its one create call, never created again: a create that lands
late does so under an id no describe ever showed, so no update computed before it, an unpause included, can target it
(a schedule deleted and recreated under one id counts its conflict token from 1 again). Its tick's identity stays the
schedule's own (`t:<tenant>:sched:<schedule>`, the action's workflow id); an incarnation is `<that>~<n>`. Every schedule
already here is backfilled as incarnation 0, under the id it may already have (`backfilled`: nothing about it before
the migration is known). Each incarnation keeps: its schedule's generation when it was recorded; when Temporal created
it; its first landed update (its generation, from its note; Temporal's update time; whether it left it paused; its
schedule's generation, read once it was seen), committed before any later update is sent to it; when the first update that unpauses it was sent (committed before the
call: one without it never fired); when a describe last showed it; the count of firings Temporal missed past its
catch-up window, as last read; and when the stray check last described it (`checked_at`): every incarnation that isn't
current, its schedule's deleted or not, is described again every hour, for good (`stray_incarnations()` lists them,
across active tenants), and one found is deleted.

`schedule_intervals` (D3f; the owner's ruling, B): the spans a schedule's missed firings are accounted over, persisted
with their boundaries, class and fixed reason. `creation`: from an incarnation's recording (its schedule's creation,
for a schedule's first) to its first landed update. Certainly missed, counted, only if the generation (which every
change of the schedule's, its workflow's or its tenant's state raises, and which only rises) is the same at its
recording, in that update's note and once the update was seen, and the update unpaused it; intentionally disabled if the same but paused; else unknown (also when it can't be counted
any more: its incarnation went first). `lost`: from the last evidence of an incarnation that went (its first landed
update; else the start of its wait; its recording, for one from before the migration) to its successor's recording:
possibly missed if it may have fired (it was sent an unpause, or its first update unpaused it), else unknown; never
counted, as seeing it unpaused proves it could fire, not that a tick did. `deleted`: a schedule deleted before its
incarnation's first update landed, or whose incarnation no describe found at or after the deletion (`seen_at`): the
same classes, to the deletion. `schedules.creation_misses` sums the counted ones. Anything possibly missed or unknown
leaves the schedule's accounting incomplete, which the API shows, as does a wait with no span yet (pending: the API
reads `schedule_incarnations` for it). Every schedule already here gets its life before the migration as an unknown
`creation` span of its incarnation 0 (`before_migration`, from its creation to the migration): nothing about it was
recorded as evidence (the owner's review), so no such schedule's accounting is ever shown complete.
`schedules.creation_misses`: firings due while a newly created schedule stayed paused, before its unpause (D3f): Temporal
neither catches them up nor counts them as missed, so the sync counts them.

The insert fence: once an erasure reaches stage 60 (`fenced_at`: its executions being deleted, nothing of the tenant
runs any more), no row of the tenant is inserted into any table that holds tenant data, by any role, whatever the
writer: a trigger takes the tenant's lifecycle lock, shared, and refuses the insert (SQLSTATE DPE01). Stage 60 is
entered under that lock taken exclusively, so an insert either commits before it or sees it; an erasure reopened at an
earlier stage (a late Temporal item found) keeps its fence.

`namespace_boundaries` (D3g): the namespace-change boundary verified for the deployment's Temporal (its name, when it
was verified, and when it was found lost), which step 9's bound relies on. The verified proof of 2b-4b (D12) records
it, as the key admin; no migration does. An erasure records the boundary it relied on, and can't complete without one,
nor once it's lost. Not fenced: the audit log (kept under the audit
policy), and the retention sweep's own counts (deleted by the erasure's sweep once audited)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

STAGES = (20, 31, 32, 33, 40, 50, 60, 70, 80, 90, 100)
# Every table holding tenant data, the keys included: what the fence covers.
FENCED = ("claim_grants", "connections", "csv_mappings", "csv_uploads", "data_keys", "egress_allowlist",
          "execution_evidence", "inbound_events", "memberships", "plugin_calls", "rate_buckets", "rate_scope_keys",
          "run_inputs", "run_requests", "run_secret_index", "run_slots", "run_steps", "runs", "schedule_firings",
          "schedule_incarnations", "schedule_intervals", "schedules", "step_outputs", "tenant_event_counters",
          "tenant_event_keys", "tenant_retention", "tenant_run_limits", "trigger_bindings", "webhook_endpoints",
          "workflow_versions", "workflows")  # fmt: skip

FENCE = [
    """CREATE FUNCTION tenant_insert_fence() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp AS $$
BEGIN
  -- the tenant's lifecycle lock (core/ingress/counters.py), shared: entering stage 60 takes it exclusively
  PERFORM pg_advisory_xact_lock_shared(hashtextextended('dewpoint:tenant:' || NEW.tenant_id::text, 0));
  IF EXISTS (SELECT 1 FROM tenant_erasures e WHERE e.tenant_id = NEW.tenant_id AND e.fenced_at IS NOT NULL) THEN
    RAISE EXCEPTION 'tenant_erased' USING ERRCODE = 'DPE01';
  END IF;
  RETURN NEW;
END $$""",
    "REVOKE ALL ON FUNCTION tenant_insert_fence() FROM PUBLIC",
]

ROLES = (
    "dewpoint_api",
    "dewpoint_dispatch",
    "dewpoint_worker",
    "dewpoint_admin",
    "dewpoint_ingress",
    "dewpoint_retention",
)
STATUS = [  # a tenant's status, whatever the reader's scope: what each writer checks under the lifecycle lock
    """CREATE FUNCTION tenant_status(tenant uuid) RETURNS text LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp AS $$ SELECT status FROM tenants WHERE id = tenant $$""",
    "REVOKE ALL ON FUNCTION tenant_status(uuid) FROM PUBLIC",
    f"GRANT EXECUTE ON FUNCTION tenant_status(uuid) TO {', '.join(ROLES)}",
]
# Plugin calls (0042, plugins-3a-2): a worker takes only an active tenant's calls (the owner's review of 2b-4a v6).
# A call an erasure left queued is never run (the worker's locked check, `lifecycle.calls_allowed`, stays the final
# fence), so it mustn't stay a candidate: as many of them as a worker has free slots would be taken and skipped every
# round, holding a newer call of an active tenant back past its API's wait.
CALL_CANDIDATES = """
CREATE OR REPLACE FUNCTION plugin_call_candidates(refs text[], types text[], hashes text[], max_calls integer)
RETURNS TABLE (tenant_id uuid, id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT due.tenant_id, due.id FROM (
    SELECT c.tenant_id, c.id, c.created_at,
           row_number() OVER (PARTITION BY c.tenant_id ORDER BY c.created_at, c.id) AS turn
    FROM plugin_calls c JOIN tenants t ON t.id = c.tenant_id AND t.status = 'active'
    WHERE c.expires_at > now()
      AND (c.state = 'pending' OR (c.state = 'claimed' AND c.lease_until <= now()))
      AND ((c.kind = 'options' AND c.node_ref = ANY(refs)) OR (c.kind = 'verify' AND c.connection_type = ANY(types)))
      AND (c.type_hash IS NULL OR c.type_hash = ANY(hashes))
  ) due
  ORDER BY due.turn, due.created_at, due.id
  LIMIT max_calls
$$"""
CALL_CANDIDATES_0042 = """
CREATE OR REPLACE FUNCTION plugin_call_candidates(refs text[], types text[], hashes text[], max_calls integer)
RETURNS TABLE (tenant_id uuid, id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT due.tenant_id, due.id FROM (
    SELECT c.tenant_id, c.id, c.created_at,
           row_number() OVER (PARTITION BY c.tenant_id ORDER BY c.created_at, c.id) AS turn
    FROM plugin_calls c
    WHERE c.expires_at > now()
      AND (c.state = 'pending' OR (c.state = 'claimed' AND c.lease_until <= now()))
      AND ((c.kind = 'options' AND c.node_ref = ANY(refs)) OR (c.kind = 'verify' AND c.connection_type = ANY(types)))
      AND (c.type_hash IS NULL OR c.type_hash = ANY(hashes))
  ) due
  ORDER BY due.turn, due.created_at, due.id
  LIMIT max_calls
$$"""
ERASURES = [  # a platform admin starts, stops and retries an erasure through the API (as its role)
    "GRANT SELECT, INSERT ON tenant_erasures TO dewpoint_api",
    "GRANT UPDATE (stopped_at, stopped_by, attempts, next_attempt_at) ON tenant_erasures TO dewpoint_api",
    "GRANT SELECT ON tenant_erasure_items, tenant_erasure_known TO dewpoint_api",
]

# The retention process carries an erasure on, as `dewpoint_retention`: its record and items; the cancels of step 40; the
# keys of step 70 and every row of step 80, each under the tenant's scope; the tombstone's anonymization. Reads are by
# column, the ids a statement's conditions need: never a sealed, wrapped or tenant-written value.
NO_POLICY = (
    "csv_mappings",
    "egress_allowlist",
    "execution_evidence",
    "plugin_calls",
    "rate_buckets",
    "rate_scope_keys",
    "run_slots",
    "tenant_event_keys",
    "tenant_run_limits",
    "trigger_bindings",
)  # their policies name their roles: the
# retention role's added (0041's tables: its tenant's rows only, never an egress exception for every tenant; 0042's
# plugin calls)  # fmt: skip
READS = {
    "connections": "id, tenant_id", "csv_mappings": "workflow_id, tenant_id", "data_keys": "id, tenant_id, version",
    "memberships": "id, tenant_id, user_id", "run_slots": "run_id, tenant_id", "tenant_event_keys": "tenant_id, version",
    "tenant_run_limits": "tenant_id", "trigger_bindings": "id, tenant_id", "workflow_versions": "id, tenant_id",
    "workflows": "id, tenant_id, active_version_id", "webhook_endpoints": "pending_events, pending_bytes",
    "tenant_event_counters": "pending_events, pending_bytes",  # its tenant_id: 0037
    "egress_allowlist": "id, tenant_id", "rate_buckets": "tenant_id, scope", "rate_scope_keys": "tenant_id",  # 0041
    "plugin_calls": "id, tenant_id",  # 0042
}  # fmt: skip
# What the sweep deletes (step 80), as `dewpoint_retention`
DELETES = (
    "connections, csv_mappings, data_keys, egress_allowlist, execution_evidence, memberships, plugin_calls, "
    "rate_buckets, rate_scope_keys, run_slots, tenant_event_counters, tenant_event_keys, tenant_retention, "
    "tenant_run_limits, trigger_bindings, webhook_endpoints, workflow_versions, workflows, retention_sweep_tenants"
)
ERASER = [
    "GRANT SELECT, UPDATE ON tenant_erasures TO dewpoint_retention",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_erasure_items TO dewpoint_retention",
    "GRANT SELECT, INSERT ON tenant_erasure_known TO dewpoint_retention",
    "GRANT USAGE ON SEQUENCE tenant_erasure_items_id_seq, tenant_erasure_known_id_seq TO dewpoint_retention",
    *(
        f"CREATE POLICY {t}_erasure ON {t} TO dewpoint_retention USING (tenant_id = app_tenant_id()) "
        "WITH CHECK (tenant_id = app_tenant_id())"
        for t in NO_POLICY
    ),
    *(f"GRANT SELECT ({columns}) ON {t} TO dewpoint_retention" for t, columns in READS.items()),
    "GRANT SELECT ON execution_evidence TO dewpoint_retention",  # identifiers and times only
    f"GRANT DELETE ON {DELETES} TO dewpoint_retention",
    "GRANT UPDATE (active_version_id) ON workflows TO dewpoint_retention",  # a workflow's versions go before it
    "GRANT UPDATE (status, reason, ended_at, cancel_requested_at) ON run_requests TO dewpoint_retention",
    "GRANT UPDATE (status, reason, ended_at) ON inbound_events TO dewpoint_retention",
    "GRANT UPDATE (pending_events, pending_bytes) ON webhook_endpoints, tenant_event_counters TO dewpoint_retention",
    "GRANT EXECUTE ON FUNCTION end_unstarted_run(uuid) TO dewpoint_retention",
    "GRANT UPDATE (status, name, slug) ON tenants TO dewpoint_retention",
    "CREATE POLICY tenants_erasure ON tenants FOR UPDATE TO dewpoint_retention USING (id = app_tenant_id())",
]

# A workflow version stays immutable (0007), deletes included, but to its tenant's erasure sweep (stage 80).
VERSIONS = """CREATE OR REPLACE FUNCTION workflow_versions_immutable() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp AS $$
BEGIN
  IF TG_OP = 'DELETE' AND EXISTS (SELECT 1 FROM tenant_erasures e WHERE e.tenant_id = OLD.tenant_id AND e.step = 80)
  THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'workflow_versions rows are immutable';
END $$"""
VERSIONS_0007 = (
    "CREATE OR REPLACE FUNCTION workflow_versions_immutable() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER "
    "AS $$ BEGIN RAISE EXCEPTION 'workflow_versions rows are immutable'; END $$"
)

# The run evidence's leader pass (0039) leaves a tenant that isn't active to its erasure.
EVIDENCE_DUE = """CREATE OR REPLACE FUNCTION execution_evidence_due(max_rows integer)
RETURNS TABLE (tenant_id uuid, id bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT e.tenant_id, e.id FROM execution_evidence e JOIN tenants t ON t.id = e.tenant_id AND t.status = 'active'
    WHERE e.lost_at IS NULL AND e.next_check_at <= statement_timestamp()
    ORDER BY e.next_check_at, e.id
    LIMIT max_rows
$$"""
EVIDENCE_DUE_0039 = """CREATE OR REPLACE FUNCTION execution_evidence_due(max_rows integer)
RETURNS TABLE (tenant_id uuid, id bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT e.tenant_id, e.id FROM execution_evidence e
    WHERE e.lost_at IS NULL AND e.next_check_at <= statement_timestamp()
    ORDER BY e.next_check_at, e.id
    LIMIT max_rows
$$"""

FIRINGS = [
    "ALTER TABLE schedule_firings ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE schedule_firings FORCE ROW LEVEL SECURITY",
    "CREATE POLICY schedule_firings_scope ON schedule_firings TO dewpoint_dispatch, dewpoint_retention "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "GRANT SELECT, INSERT ON schedule_firings TO dewpoint_dispatch",
    "GRANT SELECT, DELETE ON schedule_firings TO dewpoint_retention",
]


INCARNATIONS = [
    "ALTER TABLE schedule_incarnations ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE schedule_incarnations FORCE ROW LEVEL SECURITY",
    "CREATE POLICY schedule_incarnations_scope ON schedule_incarnations TO dewpoint_api, dewpoint_dispatch, "
    "dewpoint_retention "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "GRANT SELECT, INSERT, UPDATE (misses, seen_at, checked_at, created_at, landed_generation, landed_row_generation, "
    "landed_at, landed_paused, unpause_sent_at) ON schedule_incarnations TO dewpoint_dispatch",
    "GRANT SELECT ON schedule_incarnations TO dewpoint_api",  # a wait not yet settled, shown as pending
    "GRANT SELECT, DELETE ON schedule_incarnations TO dewpoint_retention",
    # every schedule already here: incarnation 0, under the id the sync gave every schedule before
    "INSERT INTO schedule_incarnations (temporal_id, tenant_id, schedule_id, number, misses, backfilled) "
    "SELECT 't:' || tenant_id || ':sched:' || id, tenant_id, id, 0, misses, true FROM schedules",
    """CREATE FUNCTION stray_incarnations(max_rows integer) RETURNS TABLE (tenant_id uuid, temporal_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT i.tenant_id, i.temporal_id FROM schedule_incarnations i
    JOIN tenants t ON t.id = i.tenant_id AND t.status = 'active'
    WHERE (i.checked_at IS NULL OR i.checked_at < statement_timestamp() - interval '1 hour')
      AND NOT EXISTS (
        SELECT 1 FROM schedules s WHERE s.id = i.schedule_id AND s.deleted_at IS NULL
        AND i.number = (SELECT max(j.number) FROM schedule_incarnations j WHERE j.schedule_id = i.schedule_id))
    ORDER BY i.checked_at NULLS FIRST, i.temporal_id
    LIMIT max_rows
$$""",
    "REVOKE ALL ON FUNCTION stray_incarnations(integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION stray_incarnations(integer) TO dewpoint_dispatch",
]

INTERVALS = [
    "ALTER TABLE schedule_intervals ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE schedule_intervals FORCE ROW LEVEL SECURITY",
    "CREATE POLICY schedule_intervals_scope ON schedule_intervals TO dewpoint_api, dewpoint_dispatch, "
    "dewpoint_retention USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "GRANT SELECT, INSERT ON schedule_intervals TO dewpoint_dispatch",
    "GRANT USAGE ON SEQUENCE schedule_intervals_id_seq TO dewpoint_dispatch",
    "GRANT SELECT ON schedule_intervals TO dewpoint_api",
    "GRANT SELECT, DELETE ON schedule_intervals TO dewpoint_retention",
    # every schedule already here: its life before the migration, which nothing recorded as evidence, unknown
    "INSERT INTO schedule_intervals (tenant_id, schedule_id, temporal_id, kind, starts_at, ends_at, class, reason) "
    "SELECT i.tenant_id, i.schedule_id, i.temporal_id, 'creation', s.created_at, i.recorded_at, 'unknown', "
    "'before_migration' FROM schedule_incarnations i JOIN schedules s ON s.id = i.schedule_id WHERE i.backfilled",
]

# The retention process checks the deployment's recorded namespace before erasure reaches Temporal (§2.1).
RECORD = "GRANT SELECT ON platform_settings TO dewpoint_retention"
BOUNDARIES = [
    "GRANT SELECT, INSERT, UPDATE (lost_at) ON namespace_boundaries TO dewpoint_admin",
    "GRANT USAGE ON SEQUENCE namespace_boundaries_id_seq TO dewpoint_admin",
    "GRANT SELECT ON namespace_boundaries TO dewpoint_retention",
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
        sa.Column("step_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),  # entered it
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_by", sa.Uuid, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failure", sa.Text, nullable=True),  # the last failure's fixed code
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("fenced_at", sa.DateTime(timezone=True), nullable=True),  # entered stage 60: never cleared
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
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('request', 'schedule', 'run', 'execution')", name="tenant_erasure_items_kind"),
        sa.CheckConstraint("state IN ('found', 'requested', 'verified')", name="tenant_erasure_items_state"),
    )
    op.create_index("tenant_erasure_items_one", "tenant_erasure_items",
                    ["tenant_id", "step", "workflow_id", sa.text("coalesce(run_id, '')")], unique=True)  # fmt: skip
    op.create_index("tenant_erasure_items_open", "tenant_erasure_items", ["tenant_id", "step", "id"],
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
    for statement in [*FIRINGS, *STATUS, *ERASURES, *ERASER, VERSIONS, EVIDENCE_DUE, RECORD]:
        op.execute(statement)
    op.create_table(
        "namespace_boundaries",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lost_at", sa.DateTime(timezone=True), nullable=True),
    )
    for statement in BOUNDARIES:
        op.execute(statement)
    op.create_table(
        "schedule_incarnations",
        sa.Column("temporal_id", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("schedule_id", sa.Uuid, nullable=False),  # no key: a tombstone goes before its incarnations
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("misses", sa.BigInteger, nullable=False, server_default="0"),  # Temporal's, as last read
        sa.Column("backfilled", sa.Boolean, nullable=False, server_default=sa.false()),  # from before 2b-4a
        sa.Column("generation", sa.BigInteger, nullable=True),  # its schedule's, when it was recorded
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),  # Temporal's
        sa.Column("landed_generation", sa.BigInteger, nullable=True),  # its first landed update's
        sa.Column("landed_row_generation", sa.BigInteger, nullable=True),  # its schedule's, once that was seen
        sa.Column("landed_at", sa.DateTime(timezone=True), nullable=True),  # Temporal's time for it
        sa.Column("landed_paused", sa.Boolean, nullable=True),
        sa.Column("unpause_sent_at", sa.DateTime(timezone=True), nullable=True),  # before the call: else never fired
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),  # a describe last showed it
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),  # the stray check last described it
        sa.UniqueConstraint("schedule_id", "number", name="schedule_incarnations_number"),
    )
    for statement in INCARNATIONS:
        op.execute(statement)
    op.create_table(
        "schedule_intervals",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("schedule_id", sa.Uuid, nullable=False),
        sa.Column("temporal_id", sa.Text, nullable=False),  # the incarnation it accounts for
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("class", sa.Text, nullable=False),
        sa.Column("missed", sa.Integer, nullable=True),  # counted only when certainly missed
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('creation', 'lost', 'deleted')", name="schedule_intervals_kind"),
        sa.CheckConstraint(
            "class IN ('certainly_missed', 'intentionally_disabled', 'possibly_missed', 'unknown')",
            name="schedule_intervals_class",
        ),  # fmt: skip
        sa.CheckConstraint(
            "(missed IS NOT NULL) = (class IN ('certainly_missed', 'intentionally_disabled'))",
            name="schedule_intervals_counted",
        ),  # fmt: skip
        sa.UniqueConstraint("temporal_id", "kind", name="schedule_intervals_one"),
    )
    op.create_index("schedule_intervals_schedule", "schedule_intervals", ["schedule_id", "starts_at"])
    for statement in INTERVALS:
        op.execute(statement)
    op.add_column("schedules", sa.Column("creation_misses", sa.Integer, nullable=False, server_default="0"))
    op.execute("GRANT UPDATE (creation_misses) ON schedules TO dewpoint_dispatch")
    for statement in FENCE:
        op.execute(statement)
    for table in FENCED:
        op.execute(f"CREATE TRIGGER {table}_fence BEFORE INSERT ON {table} FOR EACH ROW "
                   "EXECUTE FUNCTION tenant_insert_fence()")  # fmt: skip
    op.execute(CALL_CANDIDATES)


def downgrade() -> None:
    op.execute(CALL_CANDIDATES_0042)
    for table in FENCED:
        op.execute(f"DROP TRIGGER {table}_fence ON {table}")
    op.execute("DROP FUNCTION tenant_insert_fence()")
    op.execute("DROP FUNCTION tenant_status(uuid)")
    op.execute("REVOKE SELECT ON platform_settings FROM dewpoint_retention")
    op.execute(VERSIONS_0007)
    op.execute(EVIDENCE_DUE_0039)
    op.execute("ALTER FUNCTION workflow_versions_immutable() RESET search_path")
    op.execute("DROP POLICY tenants_erasure ON tenants")
    for table in NO_POLICY:
        op.execute(f"DROP POLICY {table}_erasure ON {table}")
    for table, columns in READS.items():
        op.execute(f"REVOKE SELECT ({columns}) ON {table} FROM dewpoint_retention")
    for statement in (
        "REVOKE SELECT ON execution_evidence FROM dewpoint_retention",
        f"REVOKE DELETE ON {DELETES} FROM dewpoint_retention",
        "REVOKE UPDATE (active_version_id) ON workflows FROM dewpoint_retention",
        "REVOKE UPDATE (status, reason, ended_at, cancel_requested_at) ON run_requests FROM dewpoint_retention",
        "REVOKE UPDATE (status, reason, ended_at) ON inbound_events FROM dewpoint_retention",
        "REVOKE UPDATE (pending_events, pending_bytes) ON webhook_endpoints, tenant_event_counters "
        "FROM dewpoint_retention",
        "REVOKE EXECUTE ON FUNCTION end_unstarted_run(uuid) FROM dewpoint_retention",
        "REVOKE UPDATE (status, name, slug) ON tenants FROM dewpoint_retention",
    ):
        op.execute(statement)
    op.execute("REVOKE UPDATE (creation_misses) ON schedules FROM dewpoint_dispatch")
    op.drop_column("schedules", "creation_misses")
    op.execute("DROP FUNCTION stray_incarnations(integer)")
    op.drop_table("schedule_intervals")
    op.drop_table("schedule_incarnations")
    op.drop_table("namespace_boundaries")
    op.drop_table("schedule_firings")
    op.drop_table("tenant_erasure_known")
    op.drop_table("tenant_erasure_items")
    op.drop_table("tenant_erasures")
    op.drop_constraint("tenants_status", "tenants", type_="check")
    op.create_check_constraint("tenants_status", "tenants", "status IN ('active', 'erasing')")
