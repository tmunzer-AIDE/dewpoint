# SPDX-License-Identifier: Apache-2.0
"""a forced retirement ends the rows of the requests it cancels (engine 2b spec §7.8)

A queued request a forced retirement cancels may have a row an earlier attempt pre-created; it's made terminal with
its request, so it can't stay `running` forever (M5's transition proofs found it left so). `end_unstarted_run()` now
ends the row with its request's own reason (`user_cancelled`, `node_type_retired`, `cel_profile_retired`), and the key
admin, which runs retirements, may call it. It still ends only the row of a request of the caller's tenant scope
that is already `cancelled`."""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

BY_REASON = """
CREATE OR REPLACE FUNCTION end_unstarted_run(run uuid) RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  UPDATE runs u SET status = 'cancelled', ended_at = statement_timestamp(), error_code = r.reason
  FROM run_requests r
  WHERE u.id = run AND r.id = run AND u.tenant_id = app_tenant_id() AND r.tenant_id = app_tenant_id()
    AND u.status = 'running' AND r.status = 'cancelled'
$$"""

USER_CANCELLED = """
CREATE OR REPLACE FUNCTION end_unstarted_run(run uuid) RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  UPDATE runs SET status = 'cancelled', ended_at = statement_timestamp(), error_code = 'user_cancelled'
  WHERE id = run AND tenant_id = app_tenant_id() AND status = 'running'
    AND EXISTS (
      SELECT 1 FROM run_requests r WHERE r.id = run AND r.tenant_id = app_tenant_id() AND r.status = 'cancelled'
    )
$$"""


def upgrade() -> None:
    op.execute(BY_REASON)
    op.execute("GRANT EXECUTE ON FUNCTION end_unstarted_run(uuid) TO dewpoint_admin")


def downgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION end_unstarted_run(uuid) FROM dewpoint_admin")
    op.execute(USER_CANCELLED)
