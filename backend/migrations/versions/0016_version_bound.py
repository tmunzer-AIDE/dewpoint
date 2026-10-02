# SPDX-License-Identifier: Apache-2.0
"""a version's open-iteration cap and loop depth, computed at publish and pinned (engine 2b spec §5.3)"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Versions published before have none: a run of one schedules with the defaults (the cap, and the graph's own
    # depth). Every workflow is published again for ABI 6 anyway (spec §6.6).
    op.add_column("workflow_versions", sa.Column("open_scopes_cap", sa.Integer))
    op.add_column("workflow_versions", sa.Column("loop_depth", sa.Integer))


def downgrade() -> None:
    op.drop_column("workflow_versions", "loop_depth")
    op.drop_column("workflow_versions", "open_scopes_cap")
