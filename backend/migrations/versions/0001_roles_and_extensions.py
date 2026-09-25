# SPDX-License-Identifier: Apache-2.0
"""roles and extensions"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ROLES = ["dewpoint_api", "dewpoint_ingress", "dewpoint_dispatch", "dewpoint_worker", "dewpoint_admin"]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    for role in ROLES:
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
            f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
        )
    op.execute("GRANT USAGE ON SCHEMA public TO " + ", ".join(ROLES))


def downgrade() -> None:
    op.execute("REVOKE ALL ON SCHEMA public FROM " + ", ".join(ROLES))
    for role in ROLES:
        op.execute(f"DROP ROLE IF EXISTS {role}")
