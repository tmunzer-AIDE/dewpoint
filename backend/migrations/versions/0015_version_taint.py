# SPDX-License-Identifier: Apache-2.0
"""a version's taint: its tainted value sites and its outputs' taint map (engine 2b spec §4.1)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Versions published before have none: no tainted site recorded, and their outputs' taint unknown (null), which a
    # parent's analysis takes as tainted. Every workflow is published again for ABI 6 anyway (spec §6.6).
    op.add_column(
        "workflow_versions", sa.Column("tainted_sites", pg.JSONB, nullable=False, server_default=sa.text("'[]'"))
    )
    op.add_column("workflow_versions", sa.Column("output_taint", pg.JSONB))


def downgrade() -> None:
    op.drop_column("workflow_versions", "output_taint")
    op.drop_column("workflow_versions", "tainted_sites")
