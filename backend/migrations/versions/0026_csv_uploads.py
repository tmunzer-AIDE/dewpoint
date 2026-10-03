# SPDX-License-Identifier: Apache-2.0
"""staged CSV uploads (engine 2b spec §8.1, §14): a file's headers and cells, encrypted, owned by its uploader and
tenant, for one hour; a start consumes one by clearing its cells, so only retention ever deletes a row (§10.3)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "csv_uploads",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("owner_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workflow_id", pg.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        # The headers and cells, sealed with the tenant's key under `csv.upload`, the upload's id the context.
        sa.Column("staged", sa.LargeBinary, nullable=True),
        # A tenant-keyed HMAC of the file, for its start's audit entry: never an unkeyed hash of its content.
        sa.Column("file_digest", sa.LargeBinary, nullable=False),
        sa.Column("digest_key_version", sa.Integer, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_by", pg.UUID(as_uuid=True), nullable=True),  # the request its start froze
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(consumed_by IS NULL) = (consumed_at IS NULL)", name="csv_uploads_consumed"),
        sa.CheckConstraint("(consumed_by IS NULL) = (staged IS NOT NULL)", name="csv_uploads_staged_until_consumed"),
        sa.CheckConstraint("expires_at > created_at", name="csv_uploads_expiry"),
    )
    for statement in (
        "ALTER TABLE csv_uploads ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE csv_uploads FORCE ROW LEVEL SECURITY",
        "CREATE POLICY csv_uploads_scope ON csv_uploads TO dewpoint_api "
        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        # The API stages an upload and its start consumes it, in the start's own transaction (admission's).
        "GRANT SELECT, INSERT ON csv_uploads TO dewpoint_api",
        "GRANT UPDATE (staged, consumed_by, consumed_at) ON csv_uploads TO dewpoint_api",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("csv_uploads")
