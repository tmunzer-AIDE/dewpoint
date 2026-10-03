# SPDX-License-Identifier: Apache-2.0
"""the dispatcher's and the reconciler's reports: health evidence 2b-4's readiness checks read (engine 2b spec §10.6)

Each dispatcher instance records what it last did and when. A report claims nothing: 2b-4's readiness check decides
what's recent enough. No row-level security: like `worker_instances`, it's the platform's, not a tenant's."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dispatcher_reports",
        sa.Column("instance_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("build_id", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("details", pg.JSONB, nullable=False, server_default="{}"),
        sa.CheckConstraint("kind IN ('dispatcher', 'reconciler')", name="dispatcher_reports_kind"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON dispatcher_reports TO dewpoint_dispatch")
    op.execute("GRANT SELECT ON dispatcher_reports TO dewpoint_admin")


def downgrade() -> None:
    op.drop_table("dispatcher_reports")
