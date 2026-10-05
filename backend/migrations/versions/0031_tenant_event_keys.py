# SPDX-License-Identifier: Apache-2.0
"""tenant_event_keys: each tenant's inbound X25519 keypairs (engine 2b spec §8.3, §6.4), versioned; the private key
sealed with the tenant's data key. The API makes one with a tenant, the key admin for tenants that predate them, the
dispatcher reads them to open events; ingress never reads the table (its resolver returns the public key)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_event_keys",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("public_key", sa.LargeBinary, nullable=False),
        sa.Column("private_sealed", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("version >= 1", name="tenant_event_keys_version"),
        sa.CheckConstraint("octet_length(public_key) = 32", name="tenant_event_keys_public"),
    )
    for statement in (
        "ALTER TABLE tenant_event_keys ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE tenant_event_keys FORCE ROW LEVEL SECURITY",
        "CREATE POLICY tenant_event_keys_scope ON tenant_event_keys TO dewpoint_api, dewpoint_dispatch, dewpoint_admin "
        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        # Like data keys: the key admin keys every tenant that predates its keypair.
        "CREATE POLICY tenant_event_keys_key_admin ON tenant_event_keys TO dewpoint_admin USING (true) WITH CHECK (true)",
        "GRANT SELECT, INSERT ON tenant_event_keys TO dewpoint_api, dewpoint_admin",
        "GRANT SELECT ON tenant_event_keys TO dewpoint_dispatch",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("tenant_event_keys")
