# SPDX-License-Identifier: Apache-2.0
"""every due tenant gets its turn (engine 2b spec §7.3; the whole-branch review)

`dispatch_candidates()` picked the same oldest due tenants every cycle: tenants that couldn't start (at their limit,
waiting on a key) left their requests due, and a full batch of them kept every other tenant from being picked. It now
takes a keyset cursor, `(queued_at, request id)` of the last full pick's last tenant, and returns `queued_at` too, so
the dispatcher goes on from there, wrapping around. Still queue-selection metadata only."""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

AFTER = """
CREATE FUNCTION dispatch_candidates(max_tenants integer, after_queued_at timestamptz, after_request uuid)
RETURNS TABLE (tenant_id uuid, request_id uuid, queued_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT due.tenant_id, due.request_id, due.queued_at FROM (
    SELECT DISTINCT ON (r.tenant_id) r.tenant_id, r.id AS request_id, r.queued_at
    FROM run_requests r
    WHERE r.status = 'queued' AND r.next_attempt_at <= now()
    ORDER BY r.tenant_id, r.queued_at, r.id
  ) due
  WHERE after_queued_at IS NULL OR (due.queued_at, due.request_id) > (after_queued_at, after_request)
  ORDER BY due.queued_at, due.request_id
  LIMIT max_tenants
$$"""

OLDEST = """
CREATE FUNCTION dispatch_candidates(max_tenants integer)
RETURNS TABLE (tenant_id uuid, request_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT tenant_id, request_id FROM (
    SELECT DISTINCT ON (r.tenant_id) r.tenant_id, r.id AS request_id, r.queued_at
    FROM run_requests r
    WHERE r.status = 'queued' AND r.next_attempt_at <= now()
    ORDER BY r.tenant_id, r.queued_at, r.id
  ) due
  ORDER BY due.queued_at, due.request_id
  LIMIT max_tenants
$$"""


def upgrade() -> None:
    op.execute("DROP FUNCTION dispatch_candidates(integer)")
    op.execute(AFTER)
    op.execute("REVOKE ALL ON FUNCTION dispatch_candidates(integer, timestamptz, uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION dispatch_candidates(integer, timestamptz, uuid) TO dewpoint_dispatch")


def downgrade() -> None:
    op.execute("DROP FUNCTION dispatch_candidates(integer, timestamptz, uuid)")
    op.execute(OLDEST)
    op.execute("REVOKE ALL ON FUNCTION dispatch_candidates(integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION dispatch_candidates(integer) TO dewpoint_dispatch")
