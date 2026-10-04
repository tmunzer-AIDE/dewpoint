# SPDX-License-Identifier: Apache-2.0
"""webhook ingress's tables and functions (engine 2b spec §8.3, §14; the owner's rulings on the 2b-3b outline):
`webhook_endpoints` (with their rate buckets, quotas and counters), `tenant_event_counters`, `trigger_bindings` and
`inbound_events`, each under forced row-level security, an event and a binding tied to their endpoint's tenant by a
foreign key. Ingress gets no table privilege: only three SECURITY DEFINER functions, each with a pinned `search_path`,
closed to `PUBLIC`. One lock order for every writer of the counters: the tenant's lifecycle lock (shared), the
endpoint's row, the tenant's counter row, then event rows."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

MIB = 1024 * 1024
MAX_BODY_BYTES = 5 * MIB  # the largest body limit an endpoint may set, and ingress's global cap (its setting's bound)


def _counters() -> list[sa.Column]:
    return [
        sa.Column(name, sa.BigInteger, nullable=False, server_default="0")
        for name in ("pending_events", "pending_bytes", "retained_events", "retained_bytes")
    ]


def _quotas(pending_events: int, pending_bytes: int, retained_events: int, retained_bytes: int) -> list[sa.Column]:
    return [
        sa.Column("pending_events_max", sa.BigInteger, nullable=False, server_default=str(pending_events)),
        sa.Column("pending_bytes_max", sa.BigInteger, nullable=False, server_default=str(pending_bytes)),
        sa.Column("retained_events_max", sa.BigInteger, nullable=False, server_default=str(retained_events)),
        sa.Column("retained_bytes_max", sa.BigInteger, nullable=False, server_default=str(retained_bytes)),
    ]


def _bucket(name: str, per_s: float, burst: int) -> list[sa.Column]:
    """A token bucket: its rate, its burst, and its tokens (full to start)."""
    return [
        sa.Column(f"{name}_per_s", sa.Float, nullable=False, server_default=str(per_s)),
        sa.Column(f"{name}_burst", sa.BigInteger, nullable=False, server_default=str(burst)),
        sa.Column(f"{name}_tokens", sa.Float, nullable=False, server_default=str(burst)),
    ]


RECORD = r"""
CREATE FUNCTION record_inbound_events(
    p_endpoint uuid, p_refusal text, p_bytes_read bigint, p_ids uuid[], p_sealed bytea[], p_key_versions integer[],
    p_dedupe bytea[], p_digests bytea[]
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_environment text;
    v_tenant uuid;
    v_status text;
    e public.webhook_endpoints%ROWTYPE;
    c public.tenant_event_counters%ROWTYPE;
    v_n integer := coalesce(cardinality(p_ids), 0);
    v_refusal text := p_refusal;
    v_sealed bigint := 0;
    v_bytes bigint;
    v_events integer;
    v_now timestamptz;
    v_wait double precision;
    v_new integer[] := '{}';
    v_new_bytes bigint := 0;
    v_duplicates integer := 0;
    v_found bytea;
    v_seen boolean;
    i integer;
    j integer;
BEGIN
    SELECT environment INTO v_environment FROM public.platform_settings WHERE id = 1;
    IF v_environment IS DISTINCT FROM 'development' THEN  -- a gated prototype until 2b-4 (the owner's ruling 8)
        RETURN jsonb_build_object('outcome', 'environment');
    END IF;
    SELECT tenant_id INTO v_tenant FROM public.webhook_endpoints WHERE id = p_endpoint;  -- an endpoint's never changes
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'unknown');
    END IF;
    -- The lock order: the tenant's lifecycle lock (shared), the endpoint's row, the tenant's counter row.
    PERFORM pg_advisory_xact_lock_shared(hashtextextended('dewpoint:tenant:' || v_tenant::text, 0));
    SELECT * INTO e FROM public.webhook_endpoints WHERE id = p_endpoint FOR UPDATE;
    SELECT status INTO v_status FROM public.tenants WHERE id = v_tenant;
    IF NOT e.enabled OR v_status IS DISTINCT FROM 'active' THEN
        RETURN jsonb_build_object('outcome', 'unknown');
    END IF;
    INSERT INTO public.tenant_event_counters (tenant_id) VALUES (v_tenant) ON CONFLICT (tenant_id) DO NOTHING;
    SELECT * INTO c FROM public.tenant_event_counters WHERE tenant_id = v_tenant FOR UPDATE;

    -- The attempt's shape, checked here whatever the caller says (the owner's M1 check).
    IF v_refusal IS NULL THEN
        IF v_n = 0 OR v_n > 500
            OR cardinality(p_sealed) IS DISTINCT FROM v_n OR cardinality(p_key_versions) IS DISTINCT FROM v_n
            OR cardinality(p_dedupe) IS DISTINCT FROM v_n OR cardinality(p_digests) IS DISTINCT FROM v_n THEN
            v_refusal := 'malformed';
        ELSIF EXISTS (SELECT 1 FROM unnest(p_ids, p_sealed, p_key_versions, p_dedupe, p_digests) AS x(id, s, v, d, g)
                      WHERE x.id IS NULL OR x.s IS NULL OR x.v IS NULL OR (x.d IS NULL) <> (x.g IS NULL)
                         OR octet_length(x.d) <> 32 OR octet_length(x.g) <> 32
                         OR x.v NOT IN (SELECT k.version FROM public.tenant_event_keys k WHERE k.tenant_id = v_tenant))
              OR (SELECT count(DISTINCT x) FROM unnest(p_ids) AS x) <> v_n THEN
            v_refusal := 'malformed';
        ELSE
            SELECT coalesce(sum(octet_length(x)), 0) INTO v_sealed FROM unnest(p_sealed) AS x;
            -- Canonical bytes are at most 4.5 times the raw body (a float like `1e15` grows to
            -- `1000000000000000.0`), and sealing adds 65 bytes an event: every permitted body fits.
            IF v_sealed > 5 * e.body_limit::bigint + 128 * v_n THEN
                v_refusal := 'too_large';
            END IF;
        END IF;
    ELSIF v_refusal NOT IN ('too_large', 'malformed') THEN
        v_refusal := 'malformed';
    END IF;
    v_bytes := greatest(coalesce(p_bytes_read, 0), v_sealed, 0);
    v_events := CASE WHEN v_refusal IS NULL THEN v_n ELSE 0 END;

    -- The rate limits, by the clock as it is now, after the locks: refill, then spend before deciding anything else,
    -- and keep what's spent.
    v_now := clock_timestamp();
    e.request_tokens := least(e.request_burst, e.request_tokens + e.request_per_s * extract(epoch FROM v_now - e.refilled_at));
    e.event_tokens := least(e.event_burst, e.event_tokens + e.event_per_s * extract(epoch FROM v_now - e.refilled_at));
    e.byte_tokens := least(e.byte_burst, e.byte_tokens + e.byte_per_s * extract(epoch FROM v_now - e.refilled_at));
    c.event_tokens := least(c.event_burst, c.event_tokens + c.event_per_s * extract(epoch FROM v_now - c.refilled_at));
    c.byte_tokens := least(c.byte_burst, c.byte_tokens + c.byte_per_s * extract(epoch FROM v_now - c.refilled_at));
    v_wait := greatest(
        (1 - e.request_tokens) / e.request_per_s,
        (v_events - e.event_tokens) / e.event_per_s,
        (v_bytes - e.byte_tokens) / e.byte_per_s,
        (v_events - c.event_tokens) / c.event_per_s,
        (v_bytes - c.byte_tokens) / c.byte_per_s,
        0
    );
    IF v_wait > 0 THEN  -- short of a token: nothing spent, only the refill kept
        UPDATE public.webhook_endpoints SET request_tokens = e.request_tokens, event_tokens = e.event_tokens,
            byte_tokens = e.byte_tokens, refilled_at = v_now WHERE id = p_endpoint;
        UPDATE public.tenant_event_counters SET event_tokens = c.event_tokens, byte_tokens = c.byte_tokens,
            refilled_at = v_now WHERE tenant_id = v_tenant;
        RETURN jsonb_build_object('outcome', 'rate_limited', 'retry_after', greatest(1, ceil(v_wait))::integer);
    END IF;
    UPDATE public.webhook_endpoints SET request_tokens = e.request_tokens - 1, event_tokens = e.event_tokens - v_events,
        byte_tokens = e.byte_tokens - v_bytes, refilled_at = v_now WHERE id = p_endpoint;
    UPDATE public.tenant_event_counters SET event_tokens = c.event_tokens - v_events,
        byte_tokens = c.byte_tokens - v_bytes, refilled_at = v_now WHERE tenant_id = v_tenant;
    IF v_refusal IS NOT NULL THEN
        RETURN jsonb_build_object('outcome', v_refusal);
    END IF;

    -- Duplicates and reused ids: a plain read of committed events (ingress never locks an existing event row).
    FOR i IN 1 .. v_n LOOP
        IF p_dedupe[i] IS NULL THEN
            v_new := v_new || i;
            CONTINUE;
        END IF;
        v_seen := false;
        FOR j IN 1 .. i - 1 LOOP
            IF p_dedupe[j] = p_dedupe[i] THEN
                IF p_digests[j] <> p_digests[i] THEN
                    RETURN jsonb_build_object('outcome', 'event_id_reused');
                END IF;
                v_seen := true;
                EXIT;
            END IF;
        END LOOP;
        IF v_seen THEN
            v_duplicates := v_duplicates + 1;
            CONTINUE;
        END IF;
        SELECT content_digest INTO v_found FROM public.inbound_events
         WHERE tenant_id = v_tenant AND endpoint_id = p_endpoint AND dedupe_key = p_dedupe[i];
        IF FOUND THEN
            IF v_found <> p_digests[i] THEN
                RETURN jsonb_build_object('outcome', 'event_id_reused');
            END IF;
            v_duplicates := v_duplicates + 1;
        ELSE
            v_new := v_new || i;
        END IF;
    END LOOP;
    SELECT coalesce(sum(octet_length(p_sealed[k])), 0) INTO v_new_bytes FROM unnest(v_new) AS k;

    -- The retained caps first (nothing frees them before 2b-4), then the pending quotas; duplicates bypass both.
    IF e.retained_events + cardinality(v_new) > e.retained_events_max OR e.retained_bytes + v_new_bytes > e.retained_bytes_max
        OR c.retained_events + cardinality(v_new) > c.retained_events_max OR c.retained_bytes + v_new_bytes > c.retained_bytes_max THEN
        RETURN jsonb_build_object('outcome', 'retained_full');
    END IF;
    IF e.pending_events + cardinality(v_new) > e.pending_events_max OR e.pending_bytes + v_new_bytes > e.pending_bytes_max
        OR c.pending_events + cardinality(v_new) > c.pending_events_max OR c.pending_bytes + v_new_bytes > c.pending_bytes_max THEN
        RETURN jsonb_build_object('outcome', 'quota_exceeded', 'retry_after', 30);
    END IF;

    INSERT INTO public.inbound_events (id, tenant_id, endpoint_id, dedupe_key, content_digest, key_version, sealed, size_bytes)
    SELECT p_ids[k], v_tenant, p_endpoint, p_dedupe[k], p_digests[k], p_key_versions[k], p_sealed[k], octet_length(p_sealed[k])
      FROM unnest(v_new) AS k;
    UPDATE public.webhook_endpoints SET pending_events = pending_events + cardinality(v_new),
        pending_bytes = pending_bytes + v_new_bytes, retained_events = retained_events + cardinality(v_new),
        retained_bytes = retained_bytes + v_new_bytes WHERE id = p_endpoint;
    UPDATE public.tenant_event_counters SET pending_events = pending_events + cardinality(v_new),
        pending_bytes = pending_bytes + v_new_bytes, retained_events = retained_events + cardinality(v_new),
        retained_bytes = retained_bytes + v_new_bytes WHERE tenant_id = v_tenant;
    RETURN jsonb_build_object('outcome', 'recorded', 'accepted', cardinality(v_new), 'duplicates', v_duplicates);
END
$$"""

RESOLVE = """
CREATE FUNCTION resolve_webhook_endpoint(p_endpoint uuid)
RETURNS TABLE (
    tenant_id uuid, enabled boolean, tenant_active boolean, auth_kind text, bearer_digest bytea, hmac_secret bytea,
    signature_header text, timestamp_header text, tolerance_s integer, allowlist cidr[], body_limit integer,
    id_source text, id_pointer text, id_header text, events_pointer text, dedupe_key bytea, key_version integer,
    public_key bytea
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT e.tenant_id, e.enabled, t.status = 'active', e.auth_kind, e.bearer_digest, e.hmac_secret,
           e.signature_header, e.timestamp_header, e.tolerance_s, e.allowlist, e.body_limit, e.id_source,
           e.id_pointer, e.id_header, e.events_pointer, e.dedupe_key, k.version, k.public_key
      FROM public.webhook_endpoints e
      JOIN public.tenants t ON t.id = e.tenant_id
      LEFT JOIN LATERAL (
          SELECT version, public_key FROM public.tenant_event_keys
           WHERE tenant_event_keys.tenant_id = e.tenant_id ORDER BY version DESC LIMIT 1
      ) k ON true
     WHERE e.id = p_endpoint
$$"""

ENVIRONMENT = """
CREATE FUNCTION ingress_environment() RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT environment FROM public.platform_settings WHERE id = 1
$$"""

FUNCTIONS = (
    "ingress_environment()",
    "resolve_webhook_endpoint(uuid)",
    "record_inbound_events(uuid, text, bigint, uuid[], bytea[], integer[], bytea[], bytea[])",
)
TABLES = ("webhook_endpoints", "tenant_event_counters", "trigger_bindings", "inbound_events")


def upgrade() -> None:
    op.create_unique_constraint("workflows_tenant", "workflows", ["id", "tenant_id"])  # for a binding's workflow
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("auth_kind", sa.String(16), nullable=False),
        sa.Column("bearer_digest", sa.LargeBinary, nullable=True),
        sa.Column("hmac_secret", sa.LargeBinary, nullable=True),  # sealed under the ingress key
        sa.Column("signature_header", sa.Text, nullable=True),
        sa.Column("timestamp_header", sa.Text, nullable=True),
        sa.Column("tolerance_s", sa.Integer, nullable=False, server_default="300"),
        sa.Column("allowlist", pg.ARRAY(pg.CIDR), nullable=False, server_default="{}"),  # empty: any address
        sa.Column("body_limit", sa.Integer, nullable=False, server_default=str(MIB)),
        sa.Column("id_source", sa.String(16), nullable=False, server_default="none"),
        sa.Column("id_pointer", sa.Text, nullable=True),
        sa.Column("id_header", sa.Text, nullable=True),
        sa.Column("events_pointer", sa.Text, nullable=True),  # none: the body is one event
        sa.Column("dedupe_key", sa.LargeBinary, nullable=False),  # sealed under the ingress key
        *_bucket("request", 20, 100),
        *_bucket("event", 200, 1000),
        *_bucket("byte", 2 * MIB, 10 * MIB),
        sa.Column("refilled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *_counters(),
        *_quotas(10_000, 64 * MIB, 100_000, 512 * MIB),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("id", "tenant_id", name="webhook_endpoints_tenant"),
        sa.CheckConstraint("auth_kind IN ('bearer', 'hmac')", name="webhook_endpoints_auth_kind"),
        sa.CheckConstraint("(auth_kind = 'bearer') = (bearer_digest IS NOT NULL)", name="webhook_endpoints_bearer"),
        sa.CheckConstraint(
            "(auth_kind = 'hmac') = (hmac_secret IS NOT NULL AND signature_header IS NOT NULL "
            "AND timestamp_header IS NOT NULL)",
            name="webhook_endpoints_hmac",
        ),
        sa.CheckConstraint("tolerance_s BETWEEN 60 AND 900", name="webhook_endpoints_tolerance"),
        sa.CheckConstraint(f"body_limit BETWEEN 1 AND {MAX_BODY_BYTES}", name="webhook_endpoints_body_limit"),
        sa.CheckConstraint("id_source IN ('pointer', 'header', 'none')", name="webhook_endpoints_id_source"),
        sa.CheckConstraint("(id_source = 'pointer') = (id_pointer IS NOT NULL)", name="webhook_endpoints_id_pointer"),
        sa.CheckConstraint("(id_source = 'header') = (id_header IS NOT NULL)", name="webhook_endpoints_id_header"),
        sa.CheckConstraint(
            "request_per_s > 0 AND event_per_s > 0 AND byte_per_s > 0 AND request_burst >= 1",
            name="webhook_endpoints_rates",
        ),
        # A burst below the largest charge an endpoint permits would refuse that request for ever: 500 events, and the
        # larger of the backstop's largest sealed batch (five times the body limit, plus 128 bytes for each of 500
        # events) and the largest body ingress reads before it authenticates, the global cap (MAX_BODY_BYTES): a body
        # past a small limit is refused, and pays, for every byte read (the owner's M2 review).
        sa.CheckConstraint(
            f"event_burst >= 500 AND byte_burst >= greatest(5 * body_limit::bigint + {128 * 500}, {MAX_BODY_BYTES})",
            name="webhook_endpoints_bursts",
        ),
        sa.CheckConstraint(
            "pending_events >= 0 AND pending_bytes >= 0 AND retained_events >= 0 AND retained_bytes >= 0",
            name="webhook_endpoints_counters",
        ),
    )
    op.create_table(
        "tenant_event_counters",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), primary_key=True),
        *_bucket("event", 1000, 5000),
        *_bucket("byte", 10 * MIB, 50 * MIB),
        sa.Column("refilled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *_counters(),
        *_quotas(50_000, 256 * MIB, 250_000, 1024 * MIB),
        sa.CheckConstraint(  # the largest charge any endpoint permits (its body limit at most 5 MiB)
            f"event_per_s > 0 AND byte_per_s > 0 AND event_burst >= 500 "
            f"AND byte_burst >= {5 * MAX_BODY_BYTES + 128 * 500}",
            name="tenant_event_counters_bursts",
        ),
        sa.CheckConstraint(
            "pending_events >= 0 AND pending_bytes >= 0 AND retained_events >= 0 AND retained_bytes >= 0",
            name="tenant_event_counters_counters",
        ),
    )
    op.create_table(
        "trigger_bindings",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("filter", pg.JSONB, nullable=False, server_default="[]"),  # typed JSON-pointer equalities, all held
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["endpoint_id", "tenant_id"],
            ["webhook_endpoints.id", "webhook_endpoints.tenant_id"],
            name="trigger_bindings_endpoint",
        ),
        sa.ForeignKeyConstraint(  # a workflow of the binding's own tenant (the owner's M1 review)
            ["workflow_id", "tenant_id"], ["workflows.id", "workflows.tenant_id"], name="trigger_bindings_workflow"
        ),
        sa.UniqueConstraint("tenant_id", "endpoint_id", "workflow_id", name="trigger_bindings_one"),
        sa.CheckConstraint(
            "jsonb_typeof(filter) = 'array' AND jsonb_array_length(filter) <= 8", name="trigger_bindings_filter"
        ),
    )
    op.create_table(
        "inbound_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("dedupe_key", sa.LargeBinary, nullable=True),
        sa.Column("content_digest", sa.LargeBinary, nullable=True),
        sa.Column("key_version", sa.Integer, nullable=False),
        sa.Column("sealed", sa.LargeBinary, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_count", sa.Integer, nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["endpoint_id", "tenant_id"],
            ["webhook_endpoints.id", "webhook_endpoints.tenant_id"],
            name="inbound_events_endpoint",
        ),
        sa.UniqueConstraint("tenant_id", "endpoint_id", "dedupe_key", name="inbound_events_dedupe"),
        sa.CheckConstraint(
            "status IN ('pending', 'matched', 'unmatched', 'cancelled', 'dead')", name="inbound_events_status"
        ),
        sa.CheckConstraint("(dedupe_key IS NULL) = (content_digest IS NULL)", name="inbound_events_identity"),
        sa.CheckConstraint("size_bytes = octet_length(sealed)", name="inbound_events_size"),
        sa.CheckConstraint("(status = 'pending') = (ended_at IS NULL)", name="inbound_events_ended"),
    )
    op.create_index("inbound_events_pending", "inbound_events", ["tenant_id", "received_at"],
                    postgresql_where=sa.text("status = 'pending'"))  # fmt: skip
    statements = [
        *(
            statement
            for table in TABLES
            for statement in (
                f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
                f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
                f"CREATE POLICY {table}_scope ON {table} TO dewpoint_api, dewpoint_dispatch "
                "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
            )
        ),
        # The API manages endpoints and bindings and reads events; the dispatcher matches. Ingress: no table at all.
        # Never how an endpoint authenticates or where its ids are: the API's role has no grant to change them (the
        # owner's docs review), since they decide how its later deliveries are checked and deduplicated. Nor its rates,
        # which the API never writes: least privilege, not a ceiling, since the role still inserts every column of a
        # new endpoint and updates the byte burst a larger body limit needs.
        "GRANT SELECT, INSERT ON webhook_endpoints TO dewpoint_api",
        "GRANT UPDATE (name, enabled, bearer_digest, hmac_secret, signature_header, timestamp_header, tolerance_s, "
        "allowlist, body_limit, events_pointer, byte_burst, updated_at) ON webhook_endpoints TO dewpoint_api",
        "GRANT SELECT ON webhook_endpoints TO dewpoint_dispatch",
        "GRANT UPDATE (pending_events, pending_bytes, retained_events, retained_bytes) ON webhook_endpoints "
        "TO dewpoint_dispatch",
        "GRANT SELECT, INSERT ON tenant_event_counters TO dewpoint_api",
        "GRANT SELECT ON tenant_event_counters TO dewpoint_dispatch",
        "GRANT UPDATE (pending_events, pending_bytes, retained_events, retained_bytes) ON tenant_event_counters "
        "TO dewpoint_dispatch",
        "GRANT SELECT, INSERT, DELETE ON trigger_bindings TO dewpoint_api",
        "GRANT UPDATE (filter, enabled) ON trigger_bindings TO dewpoint_api",
        "GRANT SELECT ON trigger_bindings TO dewpoint_dispatch",
        "GRANT SELECT ON inbound_events TO dewpoint_api, dewpoint_dispatch",
        "GRANT UPDATE (status, reason, attempts, next_attempt_at, request_count, ended_at) ON inbound_events "
        "TO dewpoint_dispatch",
        ENVIRONMENT,
        RESOLVE,
        RECORD,
        *(
            statement
            for function in FUNCTIONS
            for statement in (
                f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC",
                f"GRANT EXECUTE ON FUNCTION {function} TO dewpoint_ingress",
            )
        ),
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    for function in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION {function}")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_constraint("workflows_tenant", "workflows")
