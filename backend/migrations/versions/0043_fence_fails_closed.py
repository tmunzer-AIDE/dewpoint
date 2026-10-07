# SPDX-License-Identifier: Apache-2.0
"""The erasure's insert fence refuses rather than lets an insert through when its owner can't bypass row-level security
(the 2b-4a fix-pass review's R3). The fence reads the erasure's record, a table that forces row-level security, as its
owner, the migrating role, which bypasses it (deployment.md). Should that role lose it, the fence would read no record
and let every insert through; with `row_security` off for the function, the read errors instead, and so does the
insert. Nothing changes for an owner that bypasses it."""

from alembic import op

revision = "0043"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER FUNCTION tenant_insert_fence() SET row_security = off")


def downgrade() -> None:
    op.execute("ALTER FUNCTION tenant_insert_fence() RESET row_security")
