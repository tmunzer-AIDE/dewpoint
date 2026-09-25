# SPDX-License-Identifier: Apache-2.0
"""tenancy: tenants, memberships, RLS helper functions and policies"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False, unique=True),
        sa.Column("require_passkey", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "memberships",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "user_id"),
        sa.CheckConstraint("role IN ('owner','admin','editor','operator','viewer')", name="ck_memberships_role"),
    )
    op.create_index("ix_memberships_user", "memberships", ["user_id"])
    for stmt in (
        "CREATE FUNCTION app_tenant_id() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$",
        "CREATE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$",
        "ALTER TABLE memberships ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE memberships FORCE ROW LEVEL SECURITY",
        """CREATE POLICY memberships_scope ON memberships
             USING (tenant_id = app_tenant_id() OR user_id = app_user_id())
             WITH CHECK (tenant_id = app_tenant_id())""",
        "ALTER TABLE tenants ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE tenants FORCE ROW LEVEL SECURITY",
        """CREATE POLICY tenants_scope ON tenants
             USING (id = app_tenant_id()
                    OR EXISTS (SELECT 1 FROM memberships m
                               WHERE m.tenant_id = tenants.id AND m.user_id = app_user_id()))
             WITH CHECK (id = app_tenant_id())""",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON tenants, memberships TO dewpoint_api, dewpoint_admin",
        "GRANT SELECT ON tenants, memberships TO dewpoint_worker, dewpoint_dispatch",
    ):
        op.execute(stmt)  # asyncpg: one statement per execute


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenants_scope ON tenants; DROP POLICY IF EXISTS memberships_scope ON memberships;"
    )
    op.drop_table("memberships")
    op.drop_table("tenants")
    op.execute("DROP FUNCTION IF EXISTS app_tenant_id()")
    op.execute("DROP FUNCTION IF EXISTS app_user_id()")
