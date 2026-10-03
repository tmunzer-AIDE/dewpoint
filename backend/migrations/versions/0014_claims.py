# SPDX-License-Identifier: Apache-2.0
"""claims, their grants, and each run tree's secret index (engine 2b spec §3.1, §3.4, §3.7, §14)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

TABLES = ("run_inputs", "step_outputs", "claim_grants", "run_secret_index")
STATEMENTS = [
    *(
        statement
        for table in TABLES
        for statement in (
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY {table}_scope ON {table} "
            "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        )
    ),
    # A claim is written once and never changed: no role updates or deletes one. Retention (2b-4) gets its own role.
    # Admission claims a trigger and seeds the secret index; until 2b-2's dispatcher it runs as the dispatch role.
    "GRANT SELECT, INSERT ON run_inputs TO dewpoint_dispatch",
    "GRANT SELECT, INSERT, UPDATE ON run_secret_index TO dewpoint_dispatch",
    # The worker claims during a run (a sub-flow's input included), grants, resolves, and extends the index.
    "GRANT SELECT, INSERT ON run_inputs, step_outputs, claim_grants TO dewpoint_worker",
    "GRANT SELECT, INSERT, UPDATE ON run_secret_index TO dewpoint_worker",
]


def claim_columns() -> list[sa.Column]:  # type: ignore[type-arg]
    """What every claim row holds (§3.1): the value, encrypted under the purpose `claim` with the claim's id as
    context, and its authoritative metadata."""
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        # The run that produced it, its only owner (§3.4). No foreign key: a request's claims exist before its run row.
        sa.Column("owner_run_id", pg.UUID(as_uuid=True), nullable=False),
        # The root of the owner's tree: retention (§10.1) and the secret index (§3.7), never authorization.
        sa.Column("root_run_id", pg.UUID(as_uuid=True), nullable=False),
        # The JSON pointers inside the value that are tainted ("" is the whole value).
        sa.Column("sensitive_pointers", pg.JSONB, nullable=False),
        sa.Column("content_hash", sa.LargeBinary, nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "run_inputs",
        *claim_columns(),
        sa.Column("pointer", sa.Text, nullable=False),  # where in the run's input it was claimed from
        sa.CheckConstraint("octet_length(content_hash) = 32", name="run_inputs_hash"),
    )
    op.create_table(
        "step_outputs",
        *claim_columns(),
        sa.Column("kind", sa.String(16), nullable=False),
        # The producer, for tracing: a step's attempt, or the loop or scope a spill came from.
        sa.Column("step_id", pg.UUID(as_uuid=True)),
        sa.Column("iteration_key", sa.Text),
        sa.Column("attempt", sa.Integer),
        sa.CheckConstraint("octet_length(content_hash) = 32", name="step_outputs_hash"),
        sa.CheckConstraint(
            "kind IN ('output', 'cel', 'derived', 'filter', 'spill', 'segment')", name="step_outputs_kind"
        ),
    )
    op.create_table(
        "claim_grants",
        sa.Column("claim_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", pg.UUID(as_uuid=True), primary_key=True),  # the run the handle crosses to
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("granted_by", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("root_run_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "run_secret_index",
        sa.Column("root_run_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("string_count", sa.Integer, nullable=False),
        sa.Column("byte_count", sa.Integer, nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("version >= 1 AND string_count >= 0 AND byte_count >= 0", name="run_secret_index_counts"),
    )
    for table in ("run_inputs", "step_outputs", "claim_grants"):
        op.create_index(f"ix_{table}_tree", table, ["tenant_id", "root_run_id"])
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_scope ON {table}")
        op.drop_table(table)
