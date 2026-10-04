# SPDX-License-Identifier: Apache-2.0
"""the schedule sync's views across tenants (engine 2b spec §8.2): ids only, as the dispatcher's others are. The
schedules whose generation passes the one its sync last completed (a failed one retried after a minute), and the
enabled ones whose missed firings it hasn't read from Temporal for five minutes"""

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

STATEMENTS = [
    "CREATE INDEX schedules_unsynced ON schedules (updated_at, id) WHERE generation > synced_generation",
    """
CREATE FUNCTION schedule_candidates(max_schedules integer)
RETURNS TABLE (tenant_id uuid, schedule_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT s.tenant_id, s.id FROM schedules s
    WHERE s.generation > s.synced_generation
      AND (s.sync_error_at IS NULL OR s.sync_error_at < statement_timestamp() - interval '60 seconds')
    ORDER BY s.updated_at, s.id
    LIMIT max_schedules
$$""",
    """
CREATE FUNCTION schedule_miss_candidates(max_schedules integer)
RETURNS TABLE (tenant_id uuid, schedule_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT s.tenant_id, s.id FROM schedules s
    WHERE s.deleted_at IS NULL AND s.synced_generation > 0
      AND (s.misses_checked_at IS NULL OR s.misses_checked_at < statement_timestamp() - interval '5 minutes')
    ORDER BY s.misses_checked_at NULLS FIRST, s.id
    LIMIT max_schedules
$$""",
    *(
        statement
        for name in ("schedule_candidates", "schedule_miss_candidates")
        for statement in (
            f"REVOKE ALL ON FUNCTION {name}(integer) FROM PUBLIC",
            f"GRANT EXECUTE ON FUNCTION {name}(integer) TO dewpoint_dispatch",
        )
    ),
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION schedule_miss_candidates(integer)")
    op.execute("DROP FUNCTION schedule_candidates(integer)")
    op.execute("DROP INDEX schedules_unsynced")
