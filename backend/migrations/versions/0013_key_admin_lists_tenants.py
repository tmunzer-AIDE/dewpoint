# SPDX-License-Identifier: Apache-2.0
"""the key admin lists every tenant: `dewpoint keys ensure-tenants` finds those without a data key under row-level
security, not by bypassing it (engine 2b spec §6.3, plan 2b-1a's review)"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Read-only. Key administration already spans tenants in data_keys (data_keys_key_admin); writes to tenants stay
    # scoped by tenants_scope, and every other role still sees only the tenants it's scoped to.
    op.execute("CREATE POLICY tenants_key_admin ON tenants FOR SELECT TO dewpoint_admin USING (true)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenants_key_admin ON tenants")
