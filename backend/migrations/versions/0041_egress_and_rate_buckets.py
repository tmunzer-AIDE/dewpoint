# SPDX-License-Identifier: Apache-2.0
"""egress_allowlist, the platform admin's exceptions to the outbound guard (plugins-3 D8), and rate_buckets, the
per-tenant budgets of a provider's quota scopes (D9). Chained from 0034 while 2b-4a holds 0035-0040: whichever merges
second re-points its first down_revision to the other's head (D25)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0041"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "egress_allowlist",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("network", pg.CIDR, nullable=False),
        sa.Column("port_low", sa.Integer, nullable=True),
        sa.Column("port_high", sa.Integer, nullable=True),
        # NULL: every tenant, which the CLI makes explicit (D8)
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("masklen(network) > 0", name="egress_allowlist_not_everything"),
        sa.CheckConstraint("(port_low IS NULL) = (port_high IS NULL)", name="egress_allowlist_port_pair"),
        sa.CheckConstraint(
            "port_low IS NULL OR (port_low BETWEEN 1 AND 65535 AND port_high BETWEEN port_low AND 65535)",
            name="egress_allowlist_port_range",
        ),
    )
    op.create_table(
        "rate_buckets",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.String(200), nullable=False),
        sa.Column("capacity", sa.Float, nullable=False),
        sa.Column("refill_per_s", sa.Float, nullable=False),
        sa.Column("tokens", sa.Float, nullable=False),
        sa.Column("refilled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "scope"),
        sa.CheckConstraint("capacity > 0 AND refill_per_s > 0", name="rate_buckets_positive"),
        sa.CheckConstraint("tokens >= 0 AND tokens <= capacity", name="rate_buckets_tokens"),
    )
    for statement in (
        "ALTER TABLE egress_allowlist ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE egress_allowlist FORCE ROW LEVEL SECURITY",
        "CREATE POLICY egress_allowlist_scope ON egress_allowlist FOR SELECT TO dewpoint_api, dewpoint_worker "
        "USING (tenant_id IS NULL OR tenant_id = app_tenant_id())",
        "CREATE POLICY egress_allowlist_admin ON egress_allowlist TO dewpoint_admin USING (true) WITH CHECK (true)",
        "GRANT SELECT ON egress_allowlist TO dewpoint_api, dewpoint_worker",
        "GRANT SELECT, INSERT, DELETE ON egress_allowlist TO dewpoint_admin",
        "ALTER TABLE rate_buckets ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE rate_buckets FORCE ROW LEVEL SECURITY",
        "CREATE POLICY rate_buckets_scope ON rate_buckets TO dewpoint_api, dewpoint_worker "
        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        "GRANT SELECT, INSERT, UPDATE ON rate_buckets TO dewpoint_worker",
        "GRANT SELECT ON rate_buckets TO dewpoint_api",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("rate_buckets")
    op.drop_table("egress_allowlist")
