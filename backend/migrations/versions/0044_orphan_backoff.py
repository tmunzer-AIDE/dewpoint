# SPDX-License-Identifier: Apache-2.0
"""A sub-run its root's close left running is asked about again at its own time, `runs.next_check_at` (the 2b-4a
fix-pass review's R9): one whose history Temporal no longer has waits twice its last gap each time, up to a day, rather
than coming back, alerted on, every recheck; any other answer, after the reconciler's recheck. `orphan_subruns()`
takes the ones due, ids only, earliest first."""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

ORPHANS = """CREATE FUNCTION orphan_subruns(grace interval, max_rows integer)
RETURNS TABLE (tenant_id uuid, run_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT c.tenant_id, c.id FROM runs c JOIN runs r ON r.id = c.root_run_id AND r.tenant_id = c.tenant_id
  WHERE c.status = 'running' AND c.parent_run_id IS NOT NULL AND r.status <> 'running'
    AND r.ended_at < statement_timestamp() - grace
    AND (c.next_check_at IS NULL OR c.next_check_at <= statement_timestamp())
  ORDER BY c.next_check_at NULLS FIRST, r.ended_at, c.id
  LIMIT max_rows
$$"""
ORPHANS_0037 = """CREATE FUNCTION orphan_subruns(grace interval, recheck interval, max_rows integer)
RETURNS TABLE (tenant_id uuid, run_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT c.tenant_id, c.id FROM runs c JOIN runs r ON r.id = c.root_run_id AND r.tenant_id = c.tenant_id
  WHERE c.status = 'running' AND c.parent_run_id IS NOT NULL AND r.status <> 'running'
    AND r.ended_at < statement_timestamp() - grace
    AND (c.checked_at IS NULL OR c.checked_at < statement_timestamp() - recheck)
  ORDER BY c.checked_at NULLS FIRST, r.ended_at, c.id
  LIMIT max_rows
$$"""
OPEN = sa.text("status = 'running' AND parent_run_id IS NOT NULL")


def upgrade() -> None:
    op.add_column("runs", sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_index("runs_open_subruns", "runs")
    op.create_index("runs_open_subruns", "runs", ["next_check_at", "id"], postgresql_where=OPEN)
    op.execute("DROP FUNCTION orphan_subruns(interval, interval, integer)")
    for statement in (
        ORPHANS,
        "REVOKE ALL ON FUNCTION orphan_subruns(interval, integer) FROM PUBLIC",
        "GRANT EXECUTE ON FUNCTION orphan_subruns(interval, integer) TO dewpoint_dispatch",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION orphan_subruns(interval, integer)")
    for statement in (
        ORPHANS_0037,
        "REVOKE ALL ON FUNCTION orphan_subruns(interval, interval, integer) FROM PUBLIC",
        "GRANT EXECUTE ON FUNCTION orphan_subruns(interval, interval, integer) TO dewpoint_dispatch",
    ):
        op.execute(statement)
    op.drop_index("runs_open_subruns", "runs")
    op.create_index("runs_open_subruns", "runs", ["checked_at", "id"], postgresql_where=OPEN)
    op.drop_column("runs", "next_check_at")
