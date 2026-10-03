# SPDX-License-Identifier: Apache-2.0
"""a CSV's saved default mapping (engine 2b spec §8.1; the owner's ruling 6): one per workflow, encrypted, with the
version it was saved against, and when an upload found it no longer fits the active version's declaration"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "csv_mappings",
        sa.Column("workflow_id", pg.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        # Declared names to the file's headers, sealed under `csv.mapping`, the workflow's id the context: a file's
        # header names are its data, never plain metadata.
        sa.Column("mapping", sa.LargeBinary, nullable=False),
        sa.Column("saved_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("saved_against", pg.UUID(as_uuid=True), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True),
    )
    for statement in (
        "ALTER TABLE csv_mappings ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE csv_mappings FORCE ROW LEVEL SECURITY",
        "CREATE POLICY csv_mappings_scope ON csv_mappings TO dewpoint_api "
        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        "GRANT SELECT, INSERT, UPDATE ON csv_mappings TO dewpoint_api",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("csv_mappings")
