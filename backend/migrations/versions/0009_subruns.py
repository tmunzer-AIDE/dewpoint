# SPDX-License-Identifier: Apache-2.0
"""sub-runs: a sub-flow's or a failure handler's run points at the run that started it (engine spec §8, 2a-3b)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("kind", sa.String(32), nullable=False, server_default="run"))
    op.add_column("runs", sa.Column("parent_run_id", pg.UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=True))
    op.add_column("runs", sa.Column("parent_step_id", pg.UUID(as_uuid=True), nullable=True))
    op.add_column("runs", sa.Column("parent_iteration_key", sa.Text, nullable=True))
    op.create_check_constraint("runs_kind", "runs", "kind IN ('run', 'subflow', 'failure_handler')")
    op.create_check_constraint("runs_parent", "runs", "(kind = 'run') = (parent_run_id IS NULL)")
    op.create_index("runs_children", "runs", ["parent_run_id"], postgresql_where=sa.text("parent_run_id IS NOT NULL"))
    # a sub-run's row is written by the sub-run itself, with its first projection, as the worker role
    op.execute("GRANT INSERT ON runs TO dewpoint_worker")


def downgrade() -> None:
    op.execute("REVOKE INSERT ON runs FROM dewpoint_worker")
    op.drop_index("runs_children", "runs")
    op.drop_constraint("runs_parent", "runs")
    op.drop_constraint("runs_kind", "runs")
    for column in ("parent_iteration_key", "parent_step_id", "parent_run_id", "kind"):
        op.drop_column("runs", column)
