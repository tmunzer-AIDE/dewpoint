# SPDX-License-Identifier: Apache-2.0
"""runs and their per-step projection (engine spec §8)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE runs ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE runs FORCE ROW LEVEL SECURITY",
    "CREATE POLICY runs_scope ON runs USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    # A profile's evaluator may shut down only when no non-terminal run uses it (§4.5): counted across tenants.
    "CREATE POLICY runs_platform_read ON runs FOR SELECT TO dewpoint_admin USING (true)",
    "ALTER TABLE run_steps ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE run_steps FORCE ROW LEVEL SECURITY",
    "CREATE POLICY run_steps_scope ON run_steps "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "GRANT SELECT, INSERT, UPDATE ON runs TO dewpoint_dispatch",
    "GRANT SELECT, UPDATE ON runs TO dewpoint_worker",
    "GRANT SELECT ON runs TO dewpoint_api, dewpoint_admin",
    "GRANT SELECT, INSERT, UPDATE ON run_steps TO dewpoint_worker",
    "GRANT SELECT ON run_steps TO dewpoint_api",
]
RUN_STATUSES = "status IN ('running', 'succeeded', 'failed', 'cancelled', 'deadline_exceeded')"


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("workflow_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_version_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column("iterations", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_by", pg.UUID(as_uuid=True)),
        sa.ForeignKeyConstraint(
            ["workflow_version_id", "workflow_id"],
            ["workflow_versions.id", "workflow_versions.workflow_id"],
            name="runs_version_fk",
        ),
        sa.CheckConstraint("mode IN ('live', 'simulate')", name="runs_mode"),
        sa.CheckConstraint(RUN_STATUSES, name="runs_status"),
    )
    op.create_index("runs_tenant_started", "runs", ["tenant_id", sa.text("started_at DESC"), "id"])
    op.create_index("runs_open", "runs", ["workflow_version_id"], postgresql_where=sa.text("status = 'running'"))
    op.create_table(
        "run_steps",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("step_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("iteration_key", sa.Text, primary_key=True),
        sa.Column("attempt", sa.Integer, primary_key=True),
        sa.Column("node_key", sa.String(63), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("input_preview", pg.JSONB),
        sa.Column("output_preview", pg.JSONB),
        sa.Column("error_code", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column("outcome", sa.String(16)),
        sa.Column("cel_mode", sa.String(16)),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed', 'cancelled')", name="run_steps_status"),
        sa.CheckConstraint("outcome IN ('applied', 'simulated', 'outcome_unknown')", name="run_steps_outcome"),
        sa.CheckConstraint("cel_mode IN ('local', 'activity')", name="run_steps_cel_mode"),
    )
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in ("run_steps", "runs"):
        for policy in ("scope", "platform_read"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{policy} ON {table}")
    op.drop_table("run_steps")
    op.drop_table("runs")
