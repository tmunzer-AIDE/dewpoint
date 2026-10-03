# SPDX-License-Identifier: Apache-2.0
"""the reconciler's view across tenants and its round robin (engine 2b spec §7.6)

`run_requests.checked_at`: when the reconciler last asked Temporal about a request, so each one is asked at most once
per recheck interval. `reconcile_candidates()`: like `dispatch_candidates()`, ids and a kind only, never a request's
contents: uncertain starts past their grace period, started runs whose rows are still `running`, and slots held by
runs whose rows have ended."""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

CANDIDATES = """
CREATE FUNCTION reconcile_candidates(grace interval, recheck interval, max_rows integer)
RETURNS TABLE (tenant_id uuid, request_id uuid, kind text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT c.tenant_id, c.request_id, c.kind FROM (
    SELECT r.tenant_id, r.id AS request_id, 'starting'::text AS kind, s.reserved_at AS since
    FROM run_requests r JOIN run_slots s ON s.run_id = r.id
    WHERE r.status = 'starting' AND s.reserved_at < statement_timestamp() - grace
    UNION ALL
    SELECT r.tenant_id, r.id, 'open', u.queued_at
    FROM run_requests r JOIN runs u ON u.id = r.id
    WHERE r.status = 'started' AND u.status = 'running'
    UNION ALL
    SELECT s.tenant_id, s.run_id, 'slot', s.reserved_at
    FROM run_slots s JOIN runs u ON u.id = s.run_id JOIN run_requests r ON r.id = s.run_id
    WHERE r.status <> 'starting' AND u.status <> 'running'
  ) c JOIN run_requests q ON q.id = c.request_id
  WHERE q.checked_at IS NULL OR q.checked_at < statement_timestamp() - recheck
  ORDER BY q.checked_at NULLS FIRST, c.since, c.request_id
  LIMIT max_rows
$$"""


def upgrade() -> None:
    op.add_column("run_requests", sa.Column("checked_at", sa.DateTime(timezone=True)))
    op.execute(CANDIDATES)
    op.execute("REVOKE ALL ON FUNCTION reconcile_candidates(interval, interval, integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION reconcile_candidates(interval, interval, integer) TO dewpoint_dispatch")


def downgrade() -> None:
    op.execute("DROP FUNCTION reconcile_candidates(interval, interval, integer)")
    op.drop_column("run_requests", "checked_at")
