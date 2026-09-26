# SPDX-License-Identifier: Apache-2.0
"""workflows, immutable versions, plugin registry and lifecycle states"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

INITIAL_CEL_PROFILE = "cel-cpp-0.1.3/fn-1/cls-1"
STATE_CHECK = "state IN ('active', 'deprecated', 'retired')"

STATEMENTS = [
    "ALTER TABLE workflows ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE workflows FORCE ROW LEVEL SECURITY",
    "CREATE POLICY workflows_scope ON workflows "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    # Platform lifecycle previews (retire --force) list affected workflows across tenants. Read-only.
    "CREATE POLICY workflows_platform_read ON workflows FOR SELECT TO dewpoint_admin USING (true)",
    "ALTER TABLE workflow_versions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE workflow_versions FORCE ROW LEVEL SECURITY",
    "CREATE POLICY workflow_versions_scope ON workflow_versions "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "CREATE POLICY workflow_versions_platform_read ON workflow_versions FOR SELECT TO dewpoint_admin USING (true)",
    "CREATE FUNCTION workflow_versions_immutable() RETURNS trigger LANGUAGE plpgsql AS "
    "$$ BEGIN RAISE EXCEPTION 'workflow_versions rows are immutable'; END $$",
    "CREATE TRIGGER workflow_versions_immutable BEFORE UPDATE OR DELETE ON workflow_versions "
    "FOR EACH ROW EXECUTE FUNCTION workflow_versions_immutable()",
    "GRANT SELECT, INSERT, UPDATE ON workflows TO dewpoint_api",
    "GRANT SELECT ON workflows TO dewpoint_worker, dewpoint_dispatch, dewpoint_admin",
    "GRANT SELECT, INSERT ON workflow_versions TO dewpoint_api",
    "GRANT SELECT ON workflow_versions TO dewpoint_worker, dewpoint_dispatch, dewpoint_admin",
    "GRANT SELECT ON plugin_manifests, node_type_versions, cel_profiles TO dewpoint_api, dewpoint_worker, dewpoint_dispatch",
    "GRANT SELECT, INSERT, UPDATE ON plugin_manifests, node_type_versions, cel_profiles TO dewpoint_admin",
    f"INSERT INTO cel_profiles (profile, state) VALUES ('{INITIAL_CEL_PROFILE}', 'active')",
]


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "plugin_manifests",
        sa.Column("name", sa.String(41), primary_key=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("sdk_version", sa.String(32), nullable=False),
        sa.Column("manifest", pg.JSONB, nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "node_type_versions",
        sa.Column("type", sa.String(120), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("plugin", sa.String(41), sa.ForeignKey("plugin_manifests.name"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("manifest", pg.JSONB, nullable=False),
        sa.Column("contract_hash", sa.String(64), nullable=False),  # everything but display metadata
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("state_changed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(STATE_CHECK, name="node_type_versions_state"),
    )
    op.create_table(
        "cel_profiles",
        sa.Column("profile", sa.String(120), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("state_changed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(STATE_CHECK, name="cel_profiles_state"),
    )
    op.create_table(
        "workflows",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("active_version_id", pg.UUID(as_uuid=True)),
        sa.Column("draft", pg.JSONB, nullable=False),
        sa.Column("draft_revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "name"),
    )
    op.create_table(
        "workflow_versions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("workflow_id", pg.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("graph", pg.JSONB, nullable=False),
        sa.Column("node_refs", pg.ARRAY(sa.Text), nullable=False),
        sa.Column("engine_abi", sa.Integer, nullable=False),
        sa.Column("cel_profile", sa.String(120), sa.ForeignKey("cel_profiles.profile"), nullable=False),
        sa.Column("connection_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("subflow_version_ids", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("failure_handler_version_id", pg.UUID(as_uuid=True)),
        sa.Column("input_schema", pg.JSONB, nullable=False),
        sa.Column("output_schema", pg.JSONB, nullable=False),
        sa.Column("vars_schema", pg.JSONB, nullable=False),
        sa.Column("expressions", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("closure_version_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False),
        sa.Column("closure_workflow_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False),
        sa.Column("closure_node_refs", pg.ARRAY(sa.Text), nullable=False),
        sa.Column("closure_cel_profiles", pg.ARRAY(sa.Text), nullable=False),
        sa.Column("closure_depth", sa.Integer, nullable=False),
        sa.Column("graph_hash", sa.String(64), nullable=False),  # the authored graph only
        sa.Column("version_hash", sa.String(64), nullable=False),  # graph + resolved pins + CEL profile + engine ABI
        # No foreign key: an ON DELETE action would have to UPDATE an immutable row.
        sa.Column("published_by", pg.UUID(as_uuid=True)),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_id", "number"),
        sa.UniqueConstraint("id", "workflow_id", name="workflow_versions_id_workflow"),
    )
    op.create_foreign_key(
        "workflows_active_version_fk",
        "workflows",
        "workflow_versions",
        ["active_version_id", "id"],
        ["id", "workflow_id"],
    )
    op.create_index(
        "ix_workflow_versions_closure_node_refs", "workflow_versions", ["closure_node_refs"], postgresql_using="gin"
    )
    op.create_index(
        "ix_workflow_versions_closure_cel_profiles",
        "workflow_versions",
        ["closure_cel_profiles"],
        postgresql_using="gin",
    )
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS workflow_versions_immutable ON workflow_versions")
    op.execute("DROP FUNCTION IF EXISTS workflow_versions_immutable()")
    op.execute("ALTER TABLE workflows DROP CONSTRAINT IF EXISTS workflows_active_version_fk")
    op.drop_table("workflow_versions")
    op.drop_table("workflows")
    op.drop_table("cel_profiles")
    op.drop_table("node_type_versions")
    op.drop_table("plugin_manifests")
