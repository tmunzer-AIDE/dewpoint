# SPDX-License-Identifier: Apache-2.0
"""Key lifecycle (engine 2b spec §6.4): what retiring a data-key version waits on and rewrites.

`run_duration_limits`: every maximum run duration the dispatcher, which sets each run's deadline, has started with;
the longest is the payload floor's, and a later, shorter setting never lowers it.

Re-encryption (`dewpoint keys reencrypt`, as the key admin): the admin may rewrite the sealed columns only (a claim's,
a secret index's, a staged upload's, a saved mapping's, a schedule's input, a keypair's private key), and raise a
schedule's generation, which queues its sync to seal its Temporal action again; each tenant's under its scope. The
grants limit which columns it writes, not what: that the command keeps each record's plaintext is its own behaviour,
which no grant enforces (the owner's M3 review).
`schedules.action_key_version`: the data-key version the schedule's Temporal action still names, as the sync last read
it back: an action synced before the tick contract carried the schedule's id, sealed; one written since carries
nothing (the owner's M3 ruling).

`tick_cutover` (the owner's M3 rulings): when the last dispatcher that sealed a schedule tick's payloads under its
tenant's key had stopped, unable to restart. A tenant's key made before it never retires: a tick from before may hold
it, and nothing proves its history gone. No migration records it, not even a fresh deployment's: no database state
proves that a dispatcher from before can't start later. `dewpoint keys tick-cutover --attest` records it, on the
operator's attestation.

`execution_evidence` (the owner's M3 rulings): what Temporal may still hold of each run execution, kept until Temporal
shows it gone, whatever retention deletes from `runs` (a terminal row isn't proof that Temporal closed it). A root's
evidence is written with each start attempt, before Temporal is asked: by a trigger whatever process inserts its row,
and by the dispatcher at every attempt. It goes only once Temporal refused every attempt (`unproven` false), or showed
the execution gone after its history was read; an attempt Temporal may have taken (an absence seen at one moment, an
uncertain start, a collision) leaves it `unproven`. The dispatcher's leader describes each, reads each closed
execution's history and records its chain's runs and its children (`execution_evidence_due()` lists what's due, across
tenants); `keys retire` proves each one gone. Every root already here is backfilled, unproven: what its attempts did is
unknown.

`record_inbound_events()`, derived from 0032's text, the rest of the function unchanged:
- (2b-4 ruling D10; the owner's M3 review) every event must be in the sealed layout (core/crypto/events.py: its format
  byte, at least the sealing's overhead) and name the keypair version recorded beside it, or the batch is refused
  whole (`malformed`): an event's version column and its ciphertext agree, and no other layout is stored;
- (the owner's M3 review) a well-formed batch naming a keypair version the tenant no longer has (retired after ingress
  sealed to it) is refused whole as `key_retired`, which ingress answers with a retryable 503: the retry is sealed to
  the newest keypair. It pays as any refusal does;
- (the owner's M3 review) it holds the tenant's keypair lock, shared, after its lifecycle lock, until it commits: a
  keypair's retirement, which takes it exclusively, waits for the events being recorded, and an event recorded during
  a retirement waits for it, so no stored event names a keypair that's gone."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

SEALED = {  # table: the sealed column the key admin may rewrite (connections and user_mfa: granted before)
    "run_inputs": "ciphertext",
    "step_outputs": "ciphertext",
    "run_secret_index": "ciphertext",
    "csv_uploads": "staged",
    "csv_mappings": "mapping",
    "schedules": "input, generation",
    "tenant_event_keys": "private_sealed",
    "rate_scope_keys": "sealed",  # 0041's (plugins-3 D9): re-sealed, the same key
    "plugin_calls": "result_ct",  # 0042's (plugins-3a-2): a call's answer
}
NAMED = "OR x.v NOT IN (SELECT k.version FROM public.tenant_event_keys k WHERE k.tenant_id = v_tenant))"
AGREES = (
    "OR octet_length(x.s) < 65 OR substring(x.s from 1 for 1) <> '\\x01'::bytea\n"
    "                         OR substring(x.s from 2 for 4) <> int4send(x.v))"
)  # the sealed layout: `0x01`, the keypair's version (4 bytes, big-endian), at least 65 bytes (core/crypto/events.py)
SIZED = (
    "            IF v_sealed > 5 * e.body_limit::bigint + 128 * v_n THEN\n"
    "                v_refusal := 'too_large';\n"
    "            END IF;"
)
RETIRED = (
    "            IF v_sealed > 5 * e.body_limit::bigint + 128 * v_n THEN\n"
    "                v_refusal := 'too_large';\n"
    "            ELSIF EXISTS (SELECT 1 FROM unnest(p_key_versions) AS k(v) WHERE k.v NOT IN\n"
    "                          (SELECT t.version FROM public.tenant_event_keys t WHERE t.tenant_id = v_tenant)) THEN\n"
    "                v_refusal := 'key_retired';  -- retired since ingress sealed to it: retryable\n"
    "            END IF;"
)  # checked after the shape and the size, which a retry wouldn't change
ORDER = "-- The lock order: the tenant's lifecycle lock (shared), the endpoint's row, the tenant's counter row."
LIFECYCLE = "PERFORM pg_advisory_xact_lock_shared(hashtextextended('dewpoint:tenant:' || v_tenant::text, 0));"
KEYPAIRS = {  # then the tenant's keypair lock (core/ingress/keys.py), shared: retiring a keypair takes it exclusively
    ORDER: "-- The lock order: the tenant's lifecycle lock (shared), its keypair lock (shared), the endpoint's row, the\n"
    "    -- tenant's counter row.",
    LIFECYCLE: LIFECYCLE
    + "\n    PERFORM pg_advisory_xact_lock_shared(hashtextextended('dewpoint:event-key:' || v_tenant::text, 0));",
}
SCOPED = ("csv_uploads", "csv_mappings", "schedules", "rate_scope_keys", "plugin_calls")  # their policies name their
# roles: the key admin's added


EVIDENCE = [
    "ALTER TABLE execution_evidence ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE execution_evidence FORCE ROW LEVEL SECURITY",
    "CREATE POLICY execution_evidence_scope ON execution_evidence TO dewpoint_dispatch, dewpoint_admin, dewpoint_api "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON execution_evidence TO dewpoint_dispatch",
    "GRANT USAGE ON SEQUENCE execution_evidence_id_seq TO dewpoint_dispatch",
    "GRANT SELECT, UPDATE (lost_at, seen_at, checked_at), DELETE ON execution_evidence TO dewpoint_admin",  # a proof
    "GRANT SELECT, UPDATE (unproven), DELETE ON execution_evidence TO dewpoint_api",  # a direct start
    """CREATE FUNCTION runs_evidence() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp AS $$
BEGIN
  INSERT INTO execution_evidence (tenant_id, workflow_id, started_at)
  VALUES (NEW.tenant_id, 't:' || NEW.tenant_id || ':run:' || NEW.id, statement_timestamp())
  ON CONFLICT (workflow_id) WHERE run_id IS NULL DO NOTHING;
  RETURN NEW;
END $$""",
    "REVOKE ALL ON FUNCTION runs_evidence() FROM PUBLIC",
    "CREATE TRIGGER runs_evidence AFTER INSERT ON runs FOR EACH ROW WHEN (NEW.parent_run_id IS NULL) "
    "EXECUTE FUNCTION runs_evidence()",
    """CREATE FUNCTION execution_evidence_due(max_rows integer) RETURNS TABLE (tenant_id uuid, id bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT e.tenant_id, e.id FROM execution_evidence e
    WHERE e.lost_at IS NULL AND e.next_check_at <= statement_timestamp()
    ORDER BY e.next_check_at, e.id
    LIMIT max_rows
$$""",
    "REVOKE ALL ON FUNCTION execution_evidence_due(integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION execution_evidence_due(integer) TO dewpoint_dispatch",
]


def _recorder() -> str:
    """0032's `record_inbound_events()`, as it created it."""
    spec = importlib.util.spec_from_file_location("ingress_0032", Path(__file__).with_name("0032_webhook_ingress.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("migration 0032 isn't beside this one")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    created: str = module.RECORD
    if any(created.count(anchor) != 1 for anchor in (NAMED, SIZED, *KEYPAIRS)) or (
        "CREATE FUNCTION record_inbound_events(" not in created
    ):
        raise RuntimeError("0032's record_inbound_events() isn't the text this migration changes")
    return created.replace(
        "CREATE FUNCTION record_inbound_events(", "CREATE OR REPLACE FUNCTION record_inbound_events("
    )


def upgrade() -> None:
    op.create_table(
        "run_duration_limits",
        sa.Column("days", sa.Integer, primary_key=True),
        sa.Column("first_recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("days > 0", name="run_duration_limits_days"),
    )
    for statement in (
        "GRANT SELECT, INSERT ON run_duration_limits TO dewpoint_dispatch",
        "GRANT SELECT ON run_duration_limits TO dewpoint_admin",
    ):
        op.execute(statement)
    recorder = _recorder().replace(NAMED, AGREES).replace(SIZED, RETIRED)
    for anchor, replaced in KEYPAIRS.items():
        recorder = recorder.replace(anchor, replaced)
    op.execute(recorder)
    op.add_column("schedules", sa.Column("action_key_version", sa.Integer, nullable=True))
    op.execute("GRANT UPDATE (action_key_version) ON schedules TO dewpoint_dispatch")
    op.create_table(
        "tick_cutover",
        sa.Column("id", sa.SmallInteger, primary_key=True, server_default="1"),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="tick_cutover_once"),
    )
    op.execute("GRANT SELECT, INSERT ON tick_cutover TO dewpoint_admin")
    op.create_table(
        "execution_evidence",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("workflow_id", sa.Text, nullable=False),
        sa.Column("run_id", sa.Text, nullable=True),  # none: a root recorded before its start, its chain unread
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),  # Temporal first showed it
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),  # Temporal last asked about it
        sa.Column("unproven", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lost_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("execution_evidence_root", "execution_evidence", ["workflow_id"], unique=True,
                    postgresql_where=sa.text("run_id IS NULL"))  # fmt: skip
    op.create_index("execution_evidence_run", "execution_evidence", ["workflow_id", "run_id"], unique=True,
                    postgresql_where=sa.text("run_id IS NOT NULL"))  # fmt: skip
    op.create_index("execution_evidence_due", "execution_evidence", ["next_check_at"],
                    postgresql_where=sa.text("lost_at IS NULL"))  # fmt: skip
    op.create_index("execution_evidence_tenant", "execution_evidence", ["tenant_id", "started_at"])
    for statement in EVIDENCE:
        op.execute(statement)
    op.execute(  # every root already here: what its attempts did is unknown, so it's unproven
        "INSERT INTO execution_evidence (tenant_id, workflow_id, started_at, unproven) SELECT tenant_id, "
        "'t:' || tenant_id || ':run:' || id, coalesce(started_at, queued_at), true FROM runs "
        "WHERE parent_run_id IS NULL ON CONFLICT (workflow_id) WHERE run_id IS NULL DO NOTHING"
    )
    for table, columns in SEALED.items():
        op.execute(f"GRANT SELECT, UPDATE ({columns}) ON {table} TO dewpoint_admin")
    for table in SCOPED:
        op.execute(
            f"CREATE POLICY {table}_key_admin ON {table} TO dewpoint_admin USING (tenant_id = app_tenant_id()) "
            "WITH CHECK (tenant_id = app_tenant_id())"
        )
    # Retiring a data-key version nothing needs (spec §6.4): the key admin deletes it.
    op.execute("GRANT DELETE ON data_keys, platform_keys TO dewpoint_admin")
    # The ingress key's rotation (spec §8.3): the key admin seals every endpoint's secrets again, across tenants.
    op.execute(
        "GRANT SELECT (id, hmac_secret, dedupe_key), UPDATE (hmac_secret, dedupe_key) ON webhook_endpoints "
        "TO dewpoint_admin"
    )
    op.execute(
        "CREATE POLICY webhook_endpoints_key_admin ON webhook_endpoints TO dewpoint_admin USING (true) "
        "WITH CHECK (true)"
    )
    # An older inbound keypair no stored event names, retired (spec §8.3); the key admin reads events' versions.
    op.execute("GRANT DELETE ON tenant_event_keys TO dewpoint_admin")
    op.execute("GRANT SELECT (tenant_id, key_version) ON inbound_events TO dewpoint_admin")
    op.execute(
        "CREATE POLICY inbound_events_key_admin ON inbound_events TO dewpoint_admin USING (tenant_id = app_tenant_id())"
    )


def downgrade() -> None:
    op.execute("REVOKE DELETE ON data_keys, platform_keys FROM dewpoint_admin")
    op.execute("DROP POLICY webhook_endpoints_key_admin ON webhook_endpoints")
    op.execute(
        "REVOKE SELECT (id, hmac_secret, dedupe_key), UPDATE (hmac_secret, dedupe_key) ON webhook_endpoints "
        "FROM dewpoint_admin"
    )
    op.execute("DROP POLICY inbound_events_key_admin ON inbound_events")
    op.execute("REVOKE SELECT (tenant_id, key_version) ON inbound_events FROM dewpoint_admin")
    op.execute("REVOKE DELETE ON tenant_event_keys FROM dewpoint_admin")
    for table in SCOPED:
        op.execute(f"DROP POLICY {table}_key_admin ON {table}")
    for table, columns in SEALED.items():
        op.execute(f"REVOKE UPDATE ({columns}) ON {table} FROM dewpoint_admin")
        if table != "tenant_event_keys":  # the key admin read keypairs before
            op.execute(f"REVOKE SELECT ON {table} FROM dewpoint_admin")
    op.execute("DROP TRIGGER runs_evidence ON runs")
    op.execute("DROP FUNCTION runs_evidence()")
    op.execute("DROP FUNCTION execution_evidence_due(integer)")
    op.drop_table("execution_evidence")
    op.drop_table("tick_cutover")
    op.execute("REVOKE UPDATE (action_key_version) ON schedules FROM dewpoint_dispatch")
    op.drop_column("schedules", "action_key_version")
    op.execute(_recorder())
    op.drop_table("run_duration_limits")
