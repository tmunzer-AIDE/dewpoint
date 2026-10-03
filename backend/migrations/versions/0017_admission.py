# SPDX-License-Identifier: Apache-2.0
"""admission's queue: run requests and their trigger envelopes, slots, limits, the current build (engine 2b spec §7,
§14; revision 7)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

TABLES = ("run_requests", "tenant_run_limits", "run_slots")
# The tenant-scoped policy is the operational roles' only: a policy for every role would combine (OR) with the key
# admin's narrow ones (0019) and let it do anything within a tenant scope its session sets (the owner's M1 checkpoint).
OPERATIONAL = "dewpoint_api, dewpoint_dispatch, dewpoint_worker"
SOURCES = ("manual", "rerun", "schedule", "webhook", "dev")
STATUSES = ("queued", "starting", "started", "cancelled", "refused", "dead")
TERMINAL = ("cancelled", "refused", "dead")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


STATEMENTS = [
    *(
        statement
        for table in TABLES
        for statement in (
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY {table}_scope ON {table} TO {OPERATIONAL} "
            "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        )
    ),
    # Admission runs in its caller's transaction (§7.2): the API's, the CLI's (as dispatch), 2b-3's tick and matcher.
    # It claims the trigger, seeds the secret index, stores the envelope and freezes the request; a user cancels a
    # queued request (§7.7).
    "GRANT SELECT, INSERT ON run_inputs TO dewpoint_api",
    "GRANT SELECT, INSERT, UPDATE ON run_secret_index TO dewpoint_api",
    "GRANT SELECT, INSERT ON run_requests TO dewpoint_api",
    "GRANT UPDATE (status, reason, ended_at, cancel_requested_at) ON run_requests TO dewpoint_api",
    "GRANT SELECT ON tenant_run_limits, run_slots, current_build TO dewpoint_api",
    # The dispatcher moves requests through their states, reserves slots under the tenant's limits row, pre-creates
    # the root's run row, and records the current build; it reads every tenant's queue only through
    # dispatch_candidates().
    "GRANT SELECT, INSERT, UPDATE ON run_requests TO dewpoint_dispatch",
    "GRANT SELECT, INSERT, UPDATE ON tenant_run_limits TO dewpoint_dispatch",
    "GRANT SELECT, INSERT, DELETE ON run_slots TO dewpoint_dispatch",
    "GRANT SELECT, INSERT, UPDATE ON current_build TO dewpoint_dispatch",
    # The root's end write releases its slot in the same transaction (§7.5).
    "GRANT SELECT, DELETE ON run_slots TO dewpoint_worker",
    # The dispatcher's only view across tenants: queue-selection metadata, never a request's contents (the owner's
    # ruling on the outline). The oldest due request of each tenant, FIFO among due ones (§7.3); the dispatcher then
    # locks it tenant-scoped, with SKIP LOCKED. Owned by the migrations' superuser, so it reads past row-level security.
    """
CREATE FUNCTION dispatch_candidates(max_tenants integer)
RETURNS TABLE (tenant_id uuid, request_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT tenant_id, request_id FROM (
    SELECT DISTINCT ON (r.tenant_id) r.tenant_id, r.id AS request_id, r.queued_at
    FROM run_requests r
    WHERE r.status = 'queued' AND r.next_attempt_at <= now()
    ORDER BY r.tenant_id, r.queued_at, r.id
  ) due
  ORDER BY due.queued_at, due.request_id
  LIMIT max_tenants
$$""",
    "REVOKE ALL ON FUNCTION dispatch_candidates(integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION dispatch_candidates(integer) TO dewpoint_dispatch",
]


def upgrade() -> None:
    # A tenant being erased is refused by admission and dispatch (§6.5); the erasure itself comes with its own plan.
    op.add_column(
        "tenants",
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
    )
    op.create_check_constraint("tenants_status", "tenants", "status IN ('active', 'erasing')")
    # The platform's default number of concurrent root runs per tenant (§7.5); a tenant's limits row may override it.
    op.add_column(
        "platform_settings", sa.Column("max_concurrent_runs", sa.SmallInteger, nullable=False, server_default="5")
    )
    op.create_check_constraint("platform_settings_max_concurrent", "platform_settings", "max_concurrent_runs > 0")

    # A request's trigger envelope sits beside its claims, never one of them (revision 7, §7.1): a claim always has the
    # pointer it was claimed from, the envelope none; one envelope per owner; a request can reach only its own, in its
    # own tenant.
    op.add_column("run_inputs", sa.Column("role", sa.String(16), nullable=False, server_default="claim"))
    op.alter_column("run_inputs", "pointer", nullable=True)
    op.create_check_constraint(
        "run_inputs_role",
        "run_inputs",
        "(role = 'claim' AND pointer IS NOT NULL) OR (role = 'envelope' AND pointer IS NULL)",
    )
    op.create_unique_constraint("run_inputs_envelope_ref", "run_inputs", ["id", "tenant_id", "owner_run_id", "role"])
    op.create_index(
        "run_inputs_one_envelope",
        "run_inputs",
        ["owner_run_id"],
        unique=True,
        postgresql_where=sa.text("role = 'envelope'"),
    )

    op.create_table(
        "run_requests",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),  # the run's id too, once it starts
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("workflow_id", pg.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        # The frozen version: none only for a request refused before it was frozen.
        sa.Column("workflow_version_id", pg.UUID(as_uuid=True), sa.ForeignKey("workflow_versions.id")),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True)),  # the user, for an interactive source
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        # A tenant-keyed HMAC of source, workflow, mode and input, with its key version (§7.2), never an unkeyed hash.
        sa.Column("digest", sa.LargeBinary, nullable=False),
        sa.Column("digest_key_version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(64)),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True)),  # when it became cancelled, refused or dead
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("envelope_id", pg.UUID(as_uuid=True)),
        sa.Column("envelope_role", sa.String(16), nullable=False, server_default="envelope"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="run_requests_idempotency"),
        sa.ForeignKeyConstraint(  # an envelope of this tenant, owned by this request (revision 7)
            ["envelope_id", "tenant_id", "id", "envelope_role"],
            ["run_inputs.id", "run_inputs.tenant_id", "run_inputs.owner_run_id", "run_inputs.role"],
            name="run_requests_envelope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"source IN ({_in(SOURCES)})", name="run_requests_source"),
        sa.CheckConstraint("mode IN ('live', 'simulate')", name="run_requests_mode"),
        sa.CheckConstraint(f"status IN ({_in(STATUSES)})", name="run_requests_status"),
        sa.CheckConstraint("envelope_role = 'envelope'", name="run_requests_envelope_role"),
        sa.CheckConstraint("(status = 'refused') = (envelope_id IS NULL)", name="run_requests_envelope_iff_admitted"),
        sa.CheckConstraint("status = 'refused' OR workflow_version_id IS NOT NULL", name="run_requests_frozen"),
        sa.CheckConstraint(f"(status IN ({_in(TERMINAL)})) = (ended_at IS NOT NULL)", name="run_requests_ended"),
        sa.CheckConstraint("octet_length(digest) = 32 AND attempts >= 0", name="run_requests_values"),
    )
    op.create_index(
        "run_requests_due",
        "run_requests",
        ["tenant_id", "queued_at", "id"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index("run_requests_listed", "run_requests", ["tenant_id", sa.text("queued_at DESC"), sa.text("id DESC")])

    op.create_table(
        "tenant_run_limits",  # the row whose lock serializes a tenant's slot reservations (§7.5)
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("max_concurrent", sa.SmallInteger),  # none: the platform's default
        sa.CheckConstraint("max_concurrent IS NULL OR max_concurrent > 0", name="tenant_run_limits_positive"),
    )
    op.create_table(
        "run_slots",  # one row per running root run (§7.5)
        sa.Column("run_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("run_slots_tenant", "run_slots", ["tenant_id"])
    op.create_table(
        "current_build",  # what the dispatcher last read from Temporal, for admission's ABI check (ruling 1)
        sa.Column("id", sa.SmallInteger, primary_key=True),
        sa.Column("build_id", sa.Text, nullable=False),
        sa.Column("engine_abi", sa.Integer, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="current_build_one_row"),
    )

    # A root run's row is written at dispatch, before Temporal answers (§7.3): queued at once, started when confirmed.
    op.add_column("runs", sa.Column("queued_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE runs SET queued_at = started_at")
    op.alter_column("runs", "queued_at", nullable=False, server_default=sa.func.now())
    op.alter_column("runs", "started_at", nullable=True, server_default=None)
    op.drop_index("runs_tenant_started", table_name="runs")
    op.create_index("runs_tenant_queued", "runs", ["tenant_id", sa.text("queued_at DESC"), sa.text("id DESC")])

    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS dispatch_candidates(integer)")
    op.execute("REVOKE SELECT, INSERT ON run_inputs FROM dewpoint_api")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON run_secret_index FROM dewpoint_api")
    op.drop_index("runs_tenant_queued", table_name="runs")
    op.create_index("runs_tenant_started", "runs", ["tenant_id", sa.text("started_at DESC"), "id"])
    op.execute("UPDATE runs SET started_at = queued_at WHERE started_at IS NULL")
    op.alter_column("runs", "started_at", nullable=False, server_default=sa.func.now())
    op.drop_column("runs", "queued_at")
    for table in ("current_build", *reversed(TABLES)):
        op.execute(f"DROP POLICY IF EXISTS {table}_scope ON {table}")
        op.drop_table(table)
    op.drop_index("run_inputs_one_envelope", table_name="run_inputs")
    op.drop_constraint("run_inputs_envelope_ref", "run_inputs")
    op.drop_constraint("run_inputs_role", "run_inputs")
    op.execute("DELETE FROM run_inputs WHERE role = 'envelope'")
    op.alter_column("run_inputs", "pointer", nullable=False)
    op.drop_column("run_inputs", "role")
    op.drop_constraint("platform_settings_max_concurrent", "platform_settings")
    op.drop_column("platform_settings", "max_concurrent_runs")
    op.drop_constraint("tenants_status", "tenants")
    op.drop_column("tenants", "status")
