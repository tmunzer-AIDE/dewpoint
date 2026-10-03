# SPDX-License-Identifier: Apache-2.0
"""retirement reads every tenant's unstarted requests and cancels the queued ones (engine-core §4.5, engine 2b spec §7)

A forced retirement runs as the key admin across tenants: it lists the requests that haven't started whose frozen
closure uses the entry, and cancels each queued one explicitly. The admin may move a request only from `queued` to
`cancelled`, and only a cancel's columns."""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE POLICY run_requests_platform_read ON run_requests FOR SELECT TO dewpoint_admin USING (true)")
    op.execute(
        "CREATE POLICY run_requests_platform_cancel ON run_requests FOR UPDATE TO dewpoint_admin "
        "USING (status = 'queued') WITH CHECK (status = 'cancelled')"
    )
    op.execute("GRANT SELECT ON run_requests TO dewpoint_admin")
    op.execute("GRANT UPDATE (status, reason, ended_at) ON run_requests TO dewpoint_admin")


def downgrade() -> None:
    op.execute("REVOKE UPDATE (status, reason, ended_at) ON run_requests FROM dewpoint_admin")
    op.execute("REVOKE SELECT ON run_requests FROM dewpoint_admin")
    op.execute("DROP POLICY run_requests_platform_cancel ON run_requests")
    op.execute("DROP POLICY run_requests_platform_read ON run_requests")
