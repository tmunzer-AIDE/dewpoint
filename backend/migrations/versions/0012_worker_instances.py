# SPDX-License-Identifier: Apache-2.0
"""engine worker instances: what each one's build can do, and whether it proved it lately (engine 2b spec §2.7)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_instances",
        sa.Column("instance_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("build_id", sa.Text, nullable=False),
        sa.Column("capabilities", pg.ARRAY(sa.Text), nullable=False),
        sa.Column("healthy", sa.Boolean, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_worker_instances_build_checked", "worker_instances", ["build_id", "checked_at"])
    # A platform table, with no tenant data: each worker writes its own row; the dispatcher (2b-2) and the readiness
    # checks (2b-4) read them.
    op.execute("GRANT SELECT, INSERT, UPDATE ON worker_instances TO dewpoint_worker")
    op.execute("GRANT SELECT ON worker_instances TO dewpoint_dispatch, dewpoint_admin")


def downgrade() -> None:
    op.drop_table("worker_instances")
