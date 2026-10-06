# SPDX-License-Identifier: Apache-2.0
"""plugin_calls: plugin code the worker runs for the API, outside any run (plugins-3 D3): a node's options and a
connection type's verify. The API inserts a call, waits for its answer, then deletes it; a worker of a build that has
the call's node or type claims it with a fresh token and a lease, and answers only while both hold. Neither ever
changes what was asked. Workers find calls across tenants only through `plugin_call_candidates()` (queue metadata,
each tenant taking its turn, only calls whose connection type is declared as the worker's build declares it), and
delete calls a minute past their expiry through `plugin_calls_sweep()`. A call names only its own tenant's connection.
Chained from 0041 (D25)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

CANDIDATES = """
CREATE FUNCTION plugin_call_candidates(refs text[], types text[], hashes text[], max_calls integer)
RETURNS TABLE (tenant_id uuid, id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT due.tenant_id, due.id FROM (
    SELECT c.tenant_id, c.id, c.created_at,
           row_number() OVER (PARTITION BY c.tenant_id ORDER BY c.created_at, c.id) AS turn
    FROM plugin_calls c
    WHERE c.expires_at > now()
      AND (c.state = 'pending' OR (c.state = 'claimed' AND c.lease_until <= now()))
      AND ((c.kind = 'options' AND c.node_ref = ANY(refs)) OR (c.kind = 'verify' AND c.connection_type = ANY(types)))
      AND (c.type_hash IS NULL OR c.type_hash = ANY(hashes))
  ) due
  ORDER BY due.turn, due.created_at, due.id
  LIMIT max_calls
$$"""

SWEEP = """
CREATE FUNCTION plugin_calls_sweep() RETURNS integer
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  WITH gone AS (DELETE FROM plugin_calls WHERE expires_at < now() - interval '60 seconds' RETURNING 1)
  SELECT count(*)::integer FROM gone
$$"""


def upgrade() -> None:
    # A call names its own tenant's connection only (the 3a-2 review's finding 10): the key is (tenant, connection).
    op.create_unique_constraint("connections_tenant_id_id", "connections", ["tenant_id", "id"])
    op.create_table(
        "plugin_calls",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("node_ref", sa.String(140), nullable=True),  # options: the node type version
        sa.Column("field", sa.String(64), nullable=True),  # options: its options field
        sa.Column("connection_type", sa.String(83), nullable=True),  # verify: the type
        sa.Column("connection_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("connection_revision", sa.Integer, nullable=True),  # the revision the API read
        # The synced declaration of the connection's type: only a worker that has the same serves the call (finding 8).
        sa.Column("type_hash", sa.String(64), nullable=True),
        sa.Column("query", sa.String(200), nullable=False, server_default=""),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("claim_token", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # The answer, sealed under the tenant's data key (purpose `plugin.call`, the call's id as context).
        sa.Column("result_ct", sa.LargeBinary, nullable=True),
        sa.Column("error", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('options', 'verify')", name="plugin_calls_kind"),
        sa.CheckConstraint(
            "(kind = 'options') = (node_ref IS NOT NULL AND field IS NOT NULL)", name="plugin_calls_options"
        ),
        sa.CheckConstraint(
            "(kind = 'verify') = (connection_type IS NOT NULL AND connection_id IS NOT NULL)",
            name="plugin_calls_verify",
        ),
        sa.CheckConstraint(
            "(connection_id IS NULL) = (connection_revision IS NULL AND type_hash IS NULL)", name="plugin_calls_revision"
        ),
        sa.CheckConstraint("(connection_revision IS NULL) = (type_hash IS NULL)", name="plugin_calls_type_hash"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "connection_id"], ["connections.tenant_id", "connections.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("state IN ('pending', 'claimed', 'done', 'failed')", name="plugin_calls_state"),
        sa.CheckConstraint(
            "(state = 'claimed') = (claim_token IS NOT NULL AND lease_until IS NOT NULL)", name="plugin_calls_claim"
        ),
        sa.CheckConstraint("state <> 'done' OR result_ct IS NOT NULL", name="plugin_calls_done"),
        sa.CheckConstraint("state <> 'failed' OR error IS NOT NULL", name="plugin_calls_failed"),
    )
    op.create_index(
        "plugin_calls_due", "plugin_calls", ["created_at"], postgresql_where=sa.text("state IN ('pending', 'claimed')")
    )
    op.execute(CANDIDATES)
    op.execute(SWEEP)
    for statement in (
        "ALTER TABLE plugin_calls ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE plugin_calls FORCE ROW LEVEL SECURITY",
        "CREATE POLICY plugin_calls_scope ON plugin_calls TO dewpoint_api, dewpoint_worker "
        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        "GRANT SELECT, INSERT, DELETE ON plugin_calls TO dewpoint_api",
        "GRANT SELECT ON plugin_calls TO dewpoint_worker",
        "GRANT UPDATE (state, claim_token, lease_until, result_ct, error) ON plugin_calls TO dewpoint_worker",
        "REVOKE ALL ON FUNCTION plugin_call_candidates(text[], text[], text[], integer) FROM PUBLIC",
        "GRANT EXECUTE ON FUNCTION plugin_call_candidates(text[], text[], text[], integer) TO dewpoint_worker",
        "REVOKE ALL ON FUNCTION plugin_calls_sweep() FROM PUBLIC",
        "GRANT EXECUTE ON FUNCTION plugin_calls_sweep() TO dewpoint_worker",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION plugin_calls_sweep()")
    op.execute("DROP FUNCTION plugin_call_candidates(text[], text[], text[], integer)")
    op.drop_table("plugin_calls")
    op.drop_constraint("connections_tenant_id_id", "connections", type_="unique")
