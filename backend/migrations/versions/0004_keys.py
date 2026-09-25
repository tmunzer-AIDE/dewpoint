# SPDX-License-Identifier: Apache-2.0
"""envelope-encryption keys: tenant data keys (RLS) and platform keys (narrow grants)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _key_columns() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary, nullable=False),
        sa.Column("kek_id", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "data_keys",
        *_key_columns(),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "version"),
    )
    op.create_index("ux_data_keys_active", "data_keys", ["tenant_id"], unique=True, postgresql_where=sa.text("active"))
    op.create_table("platform_keys", *_key_columns(), sa.UniqueConstraint("version"))
    op.create_index(
        "ux_platform_keys_active", "platform_keys", [sa.text("(true)")], unique=True, postgresql_where=sa.text("active")
    )
    for stmt in (
        "ALTER TABLE data_keys ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE data_keys FORCE ROW LEVEL SECURITY",
        # Services only ever touch the key of the tenant they are scoped to.
        "CREATE POLICY data_keys_tenant ON data_keys "
        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        # Key administration (status, rewrap, rotate-dek) spans tenants by design.
        "CREATE POLICY data_keys_key_admin ON data_keys TO dewpoint_admin USING (true) WITH CHECK (true)",
        "GRANT SELECT, INSERT, UPDATE ON data_keys TO dewpoint_api, dewpoint_worker, dewpoint_admin",
        # Platform keys protect user TOTP secrets: needed by the API (sign-in) and key admins, never by workers.
        "GRANT SELECT, INSERT, UPDATE ON platform_keys TO dewpoint_api, dewpoint_admin",
    ):
        op.execute(stmt)


def downgrade() -> None:
    op.drop_table("platform_keys")
    op.execute("DROP POLICY IF EXISTS data_keys_key_admin ON data_keys")
    op.execute("DROP POLICY IF EXISTS data_keys_tenant ON data_keys")
    op.drop_table("data_keys")
