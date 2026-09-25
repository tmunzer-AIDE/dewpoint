# SPDX-License-Identifier: Apache-2.0
"""envelope-encryption data keys"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_keys",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("tenant_id", pg.UUID(as_uuid=True)),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary, nullable=False),
        sa.Column("kek_id", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("scope_key", "version"),
    )
    op.create_index("ux_data_keys_active", "data_keys", ["scope_key"], unique=True, postgresql_where=sa.text("active"))
    op.execute("GRANT SELECT, INSERT, UPDATE ON data_keys TO dewpoint_api, dewpoint_worker, dewpoint_admin")


def downgrade() -> None:
    op.drop_table("data_keys")
