# SPDX-License-Identifier: Apache-2.0
"""connections: generic, typed, secrets encrypted with the tenant data key"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("config", pg.JSONB, nullable=False),
        sa.Column("secret_ct", sa.LargeBinary),
        sa.Column("status", sa.String(20), nullable=False, server_default="unverified"),
        sa.Column("status_detail", sa.String(40), nullable=False, server_default=""),
        sa.Column("privilege", sa.String(40)),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name"),
    )
    for stmt in (
        "ALTER TABLE connections ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE connections FORCE ROW LEVEL SECURITY",
        "CREATE POLICY connections_scope ON connections "
        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON connections TO dewpoint_api, dewpoint_admin",
        "GRANT SELECT ON connections TO dewpoint_worker",
    ):
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS connections_scope ON connections")
    op.drop_table("connections")
