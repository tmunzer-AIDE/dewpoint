# SPDX-License-Identifier: Apache-2.0
"""run_step_connections: the connections each step attempt opened, as they were (sub-project 4, B7; 4c-2a ruling 8).
A connection keeps its id while its config changes (`connections.revision`), so a sample's connection can't come
from the graph: the worker records its id, type, name, revision and non-secret config when an attempt opens it. No
foreign key to `connections`, which can be deleted; the record goes with its run.

Also `runs_workflow_ended`, a workflow's ended runs, newest first: where a step's newest sample is looked for
(4c-2a ruling 9).

Slot 0045 is the owner's reservation for B7 (the editor-ui-4 ledger); slot numbers name ownership, not order, so it is
chained after main's head when it was written, 0047."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0045"
down_revision = "0047"
branch_labels = None
depends_on = None

ACCESS = (
    "ALTER TABLE run_step_connections ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE run_step_connections FORCE ROW LEVEL SECURITY",
    "CREATE POLICY run_step_connections_scope ON run_step_connections "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "GRANT SELECT, INSERT ON run_step_connections TO dewpoint_worker",
    "GRANT SELECT ON run_step_connections TO dewpoint_api",
    "CREATE TRIGGER run_step_connections_fence BEFORE INSERT ON run_step_connections FOR EACH ROW "
    "EXECUTE FUNCTION tenant_insert_fence()",
)


def upgrade() -> None:
    op.create_table(
        "run_step_connections",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("step_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("iteration_key", sa.Text, primary_key=True),
        sa.Column("attempt", sa.Integer, primary_key=True),
        sa.Column("connection_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("revision", sa.Integer, primary_key=True),  # each revision an attempt opened (ruling 8)
        sa.Column("context", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id"], ["runs.id", "runs.tenant_id"], name="run_step_connections_run", ondelete="CASCADE"
        ),
    )
    for statement in ACCESS:
        op.execute(statement)
    op.create_index(
        "runs_workflow_ended",
        "runs",
        ["workflow_id", sa.text("ended_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("ended_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("runs_workflow_ended", table_name="runs")
    op.drop_table("run_step_connections")
