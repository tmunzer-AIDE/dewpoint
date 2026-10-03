# SPDX-License-Identifier: Apache-2.0
"""cancels (engine 2b spec §7.7, §7.8): the API cancels a queued request at once, and a started run through the
dispatcher

`run_requests.cancel_sent_at`: when the dispatcher sent a recorded cancel to Temporal, so it's sent once.
`end_unstarted_run()`: the API holds no write on `runs`; this ends the row an earlier attempt wrote, in the cancel's
own transaction, and only for a request of the caller's tenant already `cancelled` (a request that never started).
`cancel_candidates()`: ids only, as `dispatch_candidates()`: started runs, still running, with a cancel to send."""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

END_UNSTARTED = """
CREATE FUNCTION end_unstarted_run(run uuid) RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  UPDATE runs SET status = 'cancelled', ended_at = statement_timestamp(), error_code = 'user_cancelled'
  WHERE id = run AND tenant_id = app_tenant_id() AND status = 'running'
    AND EXISTS (
      SELECT 1 FROM run_requests r WHERE r.id = run AND r.tenant_id = app_tenant_id() AND r.status = 'cancelled'
    )
$$"""

CANDIDATES = """
CREATE FUNCTION cancel_candidates(max_rows integer)
RETURNS TABLE (tenant_id uuid, request_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT r.tenant_id, r.id FROM run_requests r JOIN runs u ON u.id = r.id
  WHERE r.status = 'started' AND r.cancel_requested_at IS NOT NULL AND r.cancel_sent_at IS NULL
    AND u.status = 'running'
  ORDER BY r.cancel_requested_at, r.id
  LIMIT max_rows
$$"""


def upgrade() -> None:
    op.add_column("run_requests", sa.Column("cancel_sent_at", sa.DateTime(timezone=True)))
    op.execute(END_UNSTARTED)
    op.execute("REVOKE ALL ON FUNCTION end_unstarted_run(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION end_unstarted_run(uuid) TO dewpoint_api")
    op.execute(CANDIDATES)
    op.execute("REVOKE ALL ON FUNCTION cancel_candidates(integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION cancel_candidates(integer) TO dewpoint_dispatch")


def downgrade() -> None:
    op.execute("DROP FUNCTION cancel_candidates(integer)")
    op.execute("DROP FUNCTION end_unstarted_run(uuid)")
    op.drop_column("run_requests", "cancel_sent_at")
