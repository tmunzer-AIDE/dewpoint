# SPDX-License-Identifier: Apache-2.0
"""the deployment's environment, its Temporal namespace and its production gate (engine 2b spec §2, plan 2b-1a)"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.SmallInteger, primary_key=True, server_default="1"),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("temporal_namespace", sa.Text, nullable=False),
        sa.Column("production_runs", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="platform_settings_one_row"),
        sa.CheckConstraint("environment IN ('production', 'development')", name="platform_settings_environment"),
        sa.CheckConstraint("temporal_namespace <> ''", name="platform_settings_namespace"),
    )
    # Recorded once: the environment and the namespace never change, and the row is never removed. The gate
    # (production_runs) is the one column that may change, and only through the audited command (2b-4).
    op.execute(
        """
        CREATE FUNCTION platform_settings_recorded_once() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'the platform settings are never removed';
            END IF;
            IF NEW.environment <> OLD.environment OR NEW.temporal_namespace <> OLD.temporal_namespace THEN
                RAISE EXCEPTION 'the environment and the Temporal namespace are recorded once';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER platform_settings_recorded_once BEFORE UPDATE OR DELETE ON platform_settings "
        "FOR EACH ROW EXECUTE FUNCTION platform_settings_recorded_once()"
    )
    op.execute("GRANT SELECT ON platform_settings TO dewpoint_api, dewpoint_dispatch, dewpoint_worker, dewpoint_admin")


def downgrade() -> None:
    op.execute("DROP TABLE platform_settings")
    op.execute("DROP FUNCTION platform_settings_recorded_once()")
