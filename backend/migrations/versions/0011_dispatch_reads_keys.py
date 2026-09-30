# SPDX-License-Identifier: Apache-2.0
"""the dispatch role reads data keys: its starts are encrypted with the tenant's key (engine 2b spec §6.3, plan 2b-1a)"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Read-only, and RLS still scopes each read to the tenant the session is set to (data_keys_tenant).
    op.execute("GRANT SELECT ON data_keys TO dewpoint_dispatch")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON data_keys FROM dewpoint_dispatch")
