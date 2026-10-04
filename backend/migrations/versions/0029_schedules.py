# SPDX-License-Identifier: Apache-2.0
"""schedules, the source of truth the dispatcher keeps Temporal in step with (engine 2b spec §8.2, §14): a cron or an
interval, a time zone, a catch-up window, a mode and the fixed input sealed under `schedule.input`; a generation every
API change raises and the one the sync last completed (by a read-back of its marker); a tombstone a deletion leaves, so
a late tick still finds what it belonged to"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("workflow_id", pg.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("cron", sa.Text, nullable=True),
        sa.Column("every_s", sa.Integer, nullable=True),
        sa.Column("offset_s", sa.Integer, nullable=False, server_default="0"),
        sa.Column("time_zone", sa.Text, nullable=False, server_default="UTC"),
        sa.Column("catchup_window_s", sa.Integer, nullable=False, server_default="600"),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("input", sa.LargeBinary, nullable=True),  # cleared by a deletion
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("generation", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("synced_generation", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("misses", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("misses_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_error", sa.String(64), nullable=True),
        sa.Column("sync_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(cron IS NULL) <> (every_s IS NULL)", name="schedules_timing"),
        sa.CheckConstraint("every_s IS NULL OR every_s >= 60", name="schedules_interval"),
        sa.CheckConstraint("offset_s >= 0 AND (every_s IS NULL OR offset_s < every_s)", name="schedules_offset"),
        sa.CheckConstraint("catchup_window_s BETWEEN 60 AND 86400", name="schedules_catchup"),
        sa.CheckConstraint("mode IN ('live', 'simulate')", name="schedules_mode"),
        sa.CheckConstraint("(deleted_at IS NULL) = (input IS NOT NULL)", name="schedules_tombstone"),
        sa.CheckConstraint("synced_generation <= generation", name="schedules_synced"),
    )
    op.create_index("schedules_workflow", "schedules", ["tenant_id", "workflow_id"])
    for statement in (
        "ALTER TABLE schedules ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE schedules FORCE ROW LEVEL SECURITY",
        "CREATE POLICY schedules_scope ON schedules TO dewpoint_api, dewpoint_dispatch "
        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        # The API writes a schedule's wanted state; the dispatcher reads it, records what its sync completed and the
        # misses Temporal counts, and its tick reads it. No role deletes one: a deletion is a tombstone.
        "GRANT SELECT, INSERT ON schedules TO dewpoint_api",
        "GRANT UPDATE (cron, every_s, offset_s, time_zone, catchup_window_s, mode, input, enabled, generation, "
        "updated_at, deleted_at) ON schedules TO dewpoint_api",
        "GRANT SELECT ON schedules TO dewpoint_dispatch",
        "GRANT UPDATE (synced_generation, misses, misses_checked_at, sync_error, sync_error_at) ON schedules "
        "TO dewpoint_dispatch",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("schedules")
