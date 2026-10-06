# SPDX-License-Identifier: Apache-2.0
"""Key lifecycle (engine 2b spec §6.4): what retiring a data-key version waits on and rewrites.

`run_duration_limits`: every maximum run duration the dispatcher, which sets each run's deadline, has started with;
the longest is the payload floor's, and a later, shorter setting never lowers it.

Re-encryption (`dewpoint keys reencrypt`, as the key admin): the admin may rewrite the sealed columns only (a claim's,
a secret index's, a staged upload's, a saved mapping's, a schedule's input, a keypair's private key), and raise a
schedule's generation, which queues its sync to seal its Temporal action again; each tenant's under its scope. The
grants limit which columns it writes, not what: that the command keeps each record's plaintext is its own behaviour,
which no grant enforces (the owner's M3 review).
`schedules.action_key_version`: the data-key version the sync last wrote the schedule's Temporal action under.

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
SCOPED = ("csv_uploads", "csv_mappings", "schedules")  # their policies name their roles: the key admin's added


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
    op.execute("REVOKE UPDATE (action_key_version) ON schedules FROM dewpoint_dispatch")
    op.drop_column("schedules", "action_key_version")
    op.execute(_recorder())
    op.drop_table("run_duration_limits")
