# SPDX-License-Identifier: Apache-2.0
"""2b-4b M3's hardening (a provisional slot, on the lineage-reconciliation list with 0049).

- **Matching pages past a busy prefix** (D9, the owner's correction; the fresh M3 review's I2): `event_candidates`
  leaves out the endpoints and tenants the dispatcher's last pass found busy, so an event behind any number of busy
  ones is reached by the next pass, by key rather than by position (a positional cursor over ranks the pass itself
  shifts matched a tenant's events out of order). Every other event keeps its tenant's order, oldest first. The
  one-argument form stays for a dispatcher of an earlier build during a rollout. Still ids and ordering only, locking
  nothing.
- **The ingress capacity** (the owner's ruling 2 on the M3 checkpoint 2): `platform_settings` gets the sustained starts
  measured on the deployment's Temporal, the headroom's share of them ingress may use, and the agreed wait a tenant's
  queued webhook requests may stand for, each checked, none set by default, set only through
  `set_ingress_capacity()`, the API's for a platform admin (D11, the ruling on checkpoint 3; audited by its caller),
  which keeps it whole while production ingress is enabled. Once the starts and the headroom are set,
  `record_inbound_events()` (derived from 0039's text, as 0039 derives it from 0032's) holds a tenant's events to their
  product and an endpoint's to that divided by its enabled bindings, a lower configured rate staying; the matcher holds
  a tenant's queued webhook requests to the cap they make with the wait (an index of those requests, built
  concurrently). Unset, the configured rates and a development-only cap.
- **A tenant's next due request** (the owner's ruling 1 on the M3 checkpoint): `dispatch_next(tenants)`, each listed
  tenant's oldest due request as `dispatch_candidates` picks it, for a cycle's further rounds. Ids and ordering only.
- **Bounded retry and recovery** (D10(1), the owner's rulings on the M3 design, rev 2), three tables of a tenant's:
  `work_failures`, an item's count of consecutive unexpected failures for one kind of work (a reconciliation's by its
  request's phase), its next try and its hold; `recovery_items`, an item a pass can't settle and why, since when;
  `operator_commands`, what an operator asked done about one, pending until the dispatcher's leader settles it (one
  pending per item and kind; an operator's idempotency key used once per tenant). Each forces row-level security as it's
  made, takes the erasure's insert fence (stage 60) before any grant, is swept at stage 80, and goes with its item under
  retention: the retention process deletes them in its sweeps as well as an erasure's, so no restrictive gate holds its
  deletes to stage 80 (as `runs`'s). The dispatcher reads and writes failures and recovery items, and settles a command
  without changing what was asked; the retention process reads their keys and deletes; no other role reaches them.

Online (D15), in steps; grants last. A new table locks nothing in use but `tenants`, briefly, for its key."""

import importlib.util
import uuid
from collections.abc import Callable
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from migrations.online import exists, grants, index, online, step, ungranted

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

# As 0025, 0048, 0021 and 0044 left them: the downgrade's, and what the skips below are added to
DISPATCH_0049 = """
CREATE FUNCTION dispatch_candidates(max_tenants integer, after_queued_at timestamptz, after_request uuid)
RETURNS TABLE (tenant_id uuid, request_id uuid, queued_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT due.tenant_id, due.request_id, due.queued_at FROM (
    SELECT DISTINCT ON (r.tenant_id) r.tenant_id, r.id AS request_id, r.queued_at
    FROM run_requests r
    WHERE r.status = 'queued' AND r.next_attempt_at <= now()
    ORDER BY r.tenant_id, r.queued_at, r.id
  ) due
  WHERE after_queued_at IS NULL OR (due.queued_at, due.request_id) > (after_queued_at, after_request)
  ORDER BY due.queued_at, due.request_id
  LIMIT max_tenants
$$"""
CANCEL_0049 = """CREATE OR REPLACE FUNCTION cancel_candidates(max_rows integer)
RETURNS TABLE (tenant_id uuid, request_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT r.tenant_id, r.id FROM run_requests r JOIN runs u ON u.id = r.id
  WHERE r.status = 'started' AND r.cancel_requested_at IS NOT NULL AND r.cancel_sent_at IS NULL
    AND u.status = 'running'
  ORDER BY r.cancel_tried_at NULLS FIRST, r.cancel_requested_at, r.id
  LIMIT max_rows
$$"""
RECONCILE_0049 = """
CREATE FUNCTION reconcile_candidates(grace interval, recheck interval, max_rows integer)
RETURNS TABLE (tenant_id uuid, request_id uuid, kind text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT c.tenant_id, c.request_id, c.kind FROM (
    SELECT r.tenant_id, r.id AS request_id, 'starting'::text AS kind, r.starting_at AS since
    FROM run_requests r
    WHERE r.status = 'starting' AND r.starting_at < statement_timestamp() - grace
    UNION ALL
    SELECT r.tenant_id, r.id, 'open', u.queued_at
    FROM run_requests r JOIN runs u ON u.id = r.id
    WHERE r.status = 'started' AND u.status = 'running'
    UNION ALL
    SELECT s.tenant_id, s.run_id, 'slot', s.reserved_at
    FROM run_slots s JOIN runs u ON u.id = s.run_id JOIN run_requests r ON r.id = s.run_id
    WHERE r.status <> 'starting' AND u.status <> 'running'
  ) c JOIN run_requests q ON q.id = c.request_id
  WHERE q.checked_at IS NULL OR q.checked_at < statement_timestamp() - recheck
  ORDER BY q.checked_at NULLS FIRST, c.since, c.request_id
  LIMIT max_rows
$$"""
ORPHANS_0049 = """CREATE FUNCTION orphan_subruns(grace interval, max_rows integer)
RETURNS TABLE (tenant_id uuid, run_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT c.tenant_id, c.id FROM runs c JOIN runs r ON r.id = c.root_run_id AND r.tenant_id = c.tenant_id
  WHERE c.status = 'running' AND c.parent_run_id IS NOT NULL AND r.status <> 'running'
    AND r.ended_at < statement_timestamp() - grace
    AND (c.next_check_at IS NULL OR c.next_check_at <= statement_timestamp())
  ORDER BY c.next_check_at NULLS FIRST, r.ended_at, c.id
  LIMIT max_rows
$$"""


def _unless(kind: str, tenant: str, item: str) -> str:
    """Unless the item's failures for `kind` leave it for now: held, or not yet due."""
    return (f"NOT EXISTS (SELECT 1 FROM work_failures f WHERE f.tenant_id = {tenant} AND f.item_id = {item} "
            f"AND f.kind = {kind} AND (f.held_at IS NOT NULL OR f.due_at > now()))")  # fmt: skip


def _skipping(prior: str, anchor: str, added: str) -> str:
    """`prior`, replaced, with `added` after `anchor` (its one line naming what the pick takes)."""
    if prior.count(anchor) != 1:
        raise ValueError(anchor)
    return prior.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1).replace(anchor, anchor + added)


CHECKED = "  WHERE q.checked_at IS NULL OR q.checked_at < statement_timestamp() - recheck\n"
SKIPPING = [
    _skipping(DISPATCH_0049, "    WHERE r.status = 'queued' AND r.next_attempt_at <= now()\n",
              "      AND " + _unless("'dispatch'", "r.tenant_id", "r.id") + "\n"),
    _skipping(CANCEL_0049, "    AND u.status = 'running'\n", "    AND " + _unless("'cancel'", "r.tenant_id", "r.id") + "\n"),
    _skipping(RECONCILE_0049.replace(CHECKED, f"  WHERE ({CHECKED.strip().removeprefix('WHERE ')})\n"),
              "statement_timestamp() - recheck)\n",
              "    AND " + _unless("'reconcile_' || c.kind", "c.tenant_id", "c.request_id") + "\n"),
    _skipping(ORPHANS_0049, "    AND (c.next_check_at IS NULL OR c.next_check_at <= statement_timestamp())\n",
              "    AND " + _unless("'subrun'", "c.tenant_id", "c.id") + "\n"),
]  # fmt: skip


def _clear(table: str, column: str) -> list[str]:
    """`{table}_clear(names, tenants, items)`: a pass's settled items lose their rows of `names` (kinds, reasons), by
    tenant and item, in one statement: the pass's pick has no tenant scope."""
    return [
        f"""CREATE FUNCTION {table}_clear(names text[], tenants uuid[], items uuid[]) RETURNS integer
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  WITH gone AS (
    DELETE FROM {table} f USING unnest(tenants, items) AS done(tenant_id, item_id)
     WHERE f.tenant_id = done.tenant_id AND f.item_id = done.item_id AND f.{column} = ANY(names)
    RETURNING 1
  )
  SELECT count(*)::integer FROM gone
$$""",
        f"REVOKE ALL ON FUNCTION {table}_clear(text[], uuid[], uuid[]) FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION {table}_clear(text[], uuid[], uuid[]) TO dewpoint_dispatch",
    ]


# Successes clear their kinds' counts; resolved items, their recovery reasons
CLEAR = [*_clear("work_failures", "kind"), *_clear("recovery_items", "reason")]

CURSOR = [
    """CREATE FUNCTION event_candidates(max_events integer, busy_endpoints uuid[], busy_tenants uuid[])
RETURNS TABLE (tenant_id uuid, event_id uuid, endpoint_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT ranked.tenant_id, ranked.id, ranked.endpoint_id FROM (
    SELECT e.tenant_id, e.id, e.endpoint_id, e.received_at,
           row_number() OVER (PARTITION BY e.tenant_id ORDER BY e.received_at, e.id) AS rank
      FROM public.inbound_events e
     WHERE e.status = 'pending' AND (e.next_attempt_at IS NULL OR e.next_attempt_at <= now())
       AND NOT (e.endpoint_id = ANY(coalesce(busy_endpoints, '{}'::uuid[])))
       AND NOT (e.tenant_id = ANY(coalesce(busy_tenants, '{}'::uuid[])))
       AND MATCH_SKIP
  ) ranked
  ORDER BY ranked.rank, ranked.received_at, ranked.id
  LIMIT max_events
$$""",
    "REVOKE ALL ON FUNCTION event_candidates(integer, uuid[], uuid[]) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION event_candidates(integer, uuid[], uuid[]) TO dewpoint_dispatch",
]
CURSOR[0] = CURSOR[0].replace("MATCH_SKIP", _unless("'match'", "e.tenant_id", "e.id"))

# The owner's ruling 1 on the M3 checkpoint: a cycle's further rounds take each tenant that has just started one, its
# next due request, as `dispatch_candidates` would pick it
NEXT = [
    f"""CREATE FUNCTION dispatch_next(tenants uuid[])
RETURNS TABLE (tenant_id uuid, request_id uuid, queued_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT due.tenant_id, due.request_id, due.queued_at FROM (
    SELECT DISTINCT ON (r.tenant_id) r.tenant_id, r.id AS request_id, r.queued_at
    FROM run_requests r
    WHERE r.tenant_id = ANY(tenants) AND r.status = 'queued' AND r.next_attempt_at <= now()
      AND {_unless("'dispatch'", "r.tenant_id", "r.id")}
    ORDER BY r.tenant_id, r.queued_at, r.id
  ) due
  ORDER BY due.queued_at, due.request_id
$$""",
    "REVOKE ALL ON FUNCTION dispatch_next(uuid[]) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION dispatch_next(uuid[]) TO dewpoint_dispatch",
]


CAPACITY = (  # the deployment's ingress capacity: none set until its admin sets it
    # NaN sorts above every number in PostgreSQL: `> 0` alone would take it, and Infinity
    "ingress_starts_per_s double precision CONSTRAINT platform_ingress_starts "
    "CHECK (ingress_starts_per_s > 0 AND ingress_starts_per_s < 'Infinity')",
    "ingress_headroom double precision "
    "CONSTRAINT platform_ingress_headroom CHECK (ingress_headroom > 0 AND ingress_headroom <= 1)",
    "ingress_queue_wait_s integer CONSTRAINT platform_ingress_queue_wait CHECK (ingress_queue_wait_s > 0)",
)
SET_CAPACITY = [  # the API's, for a platform admin (D11): the CLI asks the API
    """CREATE FUNCTION set_ingress_capacity(patch jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    p platform_settings%ROWTYPE;
    v_before jsonb;
BEGIN
    SELECT * INTO p FROM platform_settings WHERE id = 1 FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'the deployment''s environment is not recorded';
    END IF;
    v_before := jsonb_build_object('starts_per_s', p.ingress_starts_per_s, 'headroom', p.ingress_headroom,
                                   'queue_wait_s', p.ingress_queue_wait_s);
    IF patch ? 'starts_per_s' THEN p.ingress_starts_per_s := (patch->>'starts_per_s')::double precision; END IF;
    IF patch ? 'headroom' THEN p.ingress_headroom := (patch->>'headroom')::double precision; END IF;
    IF patch ? 'queue_wait_s' THEN p.ingress_queue_wait_s := (patch->>'queue_wait_s')::integer; END IF;
    -- Production ingress enabled (a production deployment with its runs on, until D14's own switch) keeps a whole
    -- capacity: never development's rates by an unset (the owner's ruling on the M3 checkpoint 3)
    IF p.environment = 'production' AND p.production_runs AND (p.ingress_starts_per_s IS NULL
        OR p.ingress_headroom IS NULL OR p.ingress_queue_wait_s IS NULL) THEN
        RAISE EXCEPTION 'production ingress needs its whole capacity' USING ERRCODE = 'DPC01';
    END IF;
    UPDATE platform_settings SET ingress_starts_per_s = p.ingress_starts_per_s, ingress_headroom = p.ingress_headroom,
        ingress_queue_wait_s = p.ingress_queue_wait_s WHERE id = 1;
    RETURN jsonb_build_object('before', v_before, 'after', jsonb_build_object(
        'starts_per_s', p.ingress_starts_per_s, 'headroom', p.ingress_headroom, 'queue_wait_s', p.ingress_queue_wait_s));
END
$$""",
    "REVOKE ALL ON FUNCTION set_ingress_capacity(jsonb) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION set_ingress_capacity(jsonb) TO dewpoint_api",
]
QUEUED_INDEX = ("CREATE INDEX CONCURRENTLY IF NOT EXISTS run_requests_queued_webhook ON run_requests (tenant_id) "
                "WHERE status = 'queued' AND source = 'webhook'")  # fmt: skip


def _recorder_0039() -> str:
    """`record_inbound_events()` as 0039 left it: 0032's text, changed as 0039 changes it."""
    spec = importlib.util.spec_from_file_location("keys_0039", Path(__file__).with_name("0039_key_lifecycle.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("migration 0039 isn't beside this one")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recorder: str = module._recorder().replace(module.NAMED, module.AGREES).replace(module.SIZED, module.RETIRED)
    for anchor, replaced in module.KEYPAIRS.items():
        recorder = recorder.replace(anchor, replaced)
    return recorder


RATES = {  # 0039's text: what it reads and how it refills and waits, the event rates derived once the capacity's set
    "    v_wait double precision;\n": "    v_wait double precision;\n    v_budget double precision;\n"
    "    v_fanout integer;\n    v_widest integer;\n    v_event_rate double precision;\n"
    "    v_tenant_rate double precision;\n",
    "    SELECT environment INTO v_environment FROM public.platform_settings WHERE id = 1;\n":
    "    SELECT environment, ingress_starts_per_s * ingress_headroom INTO v_environment, v_budget\n"
    "      FROM public.platform_settings WHERE id = 1;\n",
    "    -- The rate limits, by the clock as it is now,":
    "    -- The event rates (the owner's ruling 2 on the 2b-4b M3 checkpoint 2): once the deployment's ingress capacity\n"
    "    -- is set, the headroom's share of its measured starts divided by the enabled bindings an event can become a\n"
    "    -- request for: an endpoint's by its own, its tenant's by the most any of its endpoints has (so its requests\n"
    "    -- stay within the share however its events spread, the fresh M3 review 3's I2); a rate configured lower stays.\n"
    "    v_event_rate := e.event_per_s;\n"
    "    v_tenant_rate := c.event_per_s;\n"
    "    IF v_budget IS NOT NULL THEN\n"
    "        SELECT greatest(count(*), 1) INTO v_fanout FROM public.trigger_bindings b\n"
    "         WHERE b.tenant_id = v_tenant AND b.endpoint_id = p_endpoint AND b.enabled;\n"
    "        SELECT greatest(coalesce(max(f.n), 0), 1) INTO v_widest FROM (SELECT count(*) AS n\n"
    "          FROM public.trigger_bindings b WHERE b.tenant_id = v_tenant AND b.enabled GROUP BY b.endpoint_id) f;\n"
    "        v_event_rate := least(v_event_rate, v_budget / v_fanout);\n"
    "        v_tenant_rate := least(v_tenant_rate, v_budget / v_widest);\n"
    "    END IF;\n\n"
    "    -- The rate limits, by the clock as it is now,",
    "e.event_tokens + e.event_per_s * extract": "e.event_tokens + v_event_rate * extract",
    "(v_events - e.event_tokens) / e.event_per_s,": "(v_events - e.event_tokens) / v_event_rate,",
    "c.event_tokens + c.event_per_s * extract": "c.event_tokens + v_tenant_rate * extract",
    "(v_events - c.event_tokens) / c.event_per_s,": "(v_events - c.event_tokens) / v_tenant_rate,",
}  # fmt: skip


def _rated() -> str:
    """0039's `record_inbound_events()`, its event rates derived from the ingress capacity."""
    recorder = _recorder_0039()
    for anchor, replaced in RATES.items():
        if recorder.count(anchor) != 1:
            raise RuntimeError(f"0039's record_inbound_events() isn't the text this migration changes: {anchor!r}")
        recorder = recorder.replace(anchor, replaced)
    return recorder


KINDS = ("dispatch", "reconcile_starting", "reconcile_open", "reconcile_slot", "cancel", "match", "subrun")
REASONS = ("start_after_end", "start_history_missing", "start_unresolved", "run_history_missing",
           "slot_history_missing", "subrun_history_missing")  # fmt: skip
COMMANDS = ("record_lost_run", "record_lost_subrun", "release_lost_slot", "settle_ended")
TABLES = ("work_failures", "recovery_items", "operator_commands")


def _within(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _tenant() -> sa.Column[uuid.UUID]:
    return sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                     nullable=False)  # fmt: skip


def _secured(table: str, *roles: str) -> list[str]:
    """Its tenant's, as it's made: the dispatcher, the retention process and `roles` within their scope (D15: in its
    step)."""
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {table}_scope ON {table} TO {', '.join(('dewpoint_dispatch', 'dewpoint_retention', *roles))} "
        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    ]


def _tables() -> list[str | Callable[[], object]]:
    return [
        lambda: op.create_table(
            "work_failures",
            _tenant(),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("item_id", pg.UUID(as_uuid=True), nullable=False),
            sa.Column("errors", sa.Integer, nullable=False),
            sa.Column("last_error", sa.String(100), nullable=False),  # its type, never its text
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True),
            # an item's rows found by its id alone (the sweep's, the commands'), each kind's by all three
            sa.PrimaryKeyConstraint("tenant_id", "item_id", "kind", name="work_failures_pkey"),
            sa.CheckConstraint(f"kind IN ({_within(KINDS)})", name="work_failures_kind"),
            sa.CheckConstraint("errors > 0", name="work_failures_errors"),
        ),
        *_secured("work_failures"),
        lambda: op.create_table(
            "recovery_items",
            _tenant(),
            sa.Column("reason", sa.String(32), nullable=False),
            sa.Column("item_id", pg.UUID(as_uuid=True), nullable=False),
            sa.Column("since", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("tenant_id", "item_id", "reason", name="recovery_items_pkey"),
            sa.CheckConstraint(f"reason IN ({_within(REASONS)})", name="recovery_items_reason"),
        ),
        *_secured("recovery_items", "dewpoint_api"),
        lambda: op.create_table(
            "operator_commands",
            sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            _tenant(),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("item_id", pg.UUID(as_uuid=True), nullable=False),
            sa.Column("reason", sa.String(32), nullable=False),  # the recorded reason it was asked on
            sa.Column("incident_since", sa.DateTime(timezone=True), nullable=False),  # that reason's `since`
            sa.Column("actor_id", pg.UUID(as_uuid=True), nullable=False),
            sa.Column("idempotency_key", sa.String(100), nullable=False),
            sa.Column("evidence", sa.String(500), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("outcome", sa.String(64), nullable=True),  # a fixed code, never text
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("tenant_id", "actor_id", "idempotency_key", name="operator_commands_idempotency"),
            sa.CheckConstraint(f"kind IN ({_within(COMMANDS)})", name="operator_commands_kind"),
            sa.CheckConstraint(f"reason IN ({_within(REASONS)})", name="operator_commands_reason"),
            sa.CheckConstraint("status IN ('pending', 'applied', 'refused')", name="operator_commands_status"),
            sa.CheckConstraint("(status = 'pending') = (decided_at IS NULL)", name="operator_commands_decided"),
        ),
        lambda: op.create_index(
            "operator_commands_pending",
            "operator_commands",
            ["tenant_id", "kind", "item_id"],
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        ),
        *_secured("operator_commands", "dewpoint_api"),
    ]


def _fence(table: str) -> str:
    return f"CREATE TRIGGER {table}_fence BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION tenant_insert_fence()"


# The operator's (the owner's rulings, rev 2): the API, a platform admin's, records a command, pending, within the
# command's tenant, reading the recovery reason it acts on; never its evidence again, nor a command settled or changed
# (the leader settles it). Its restricted access to runs and run slots stays as it was: it reaches no item itself.
OPERATOR_COLUMNS = "tenant_id, kind, item_id, reason, incident_since, actor_id, idempotency_key"
OPERATOR = [
    """CREATE FUNCTION pending_commands(max_rows integer) RETURNS TABLE (tenant_id uuid, command_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT c.tenant_id, c.id FROM operator_commands c WHERE c.status = 'pending'
  ORDER BY c.requested_at, c.id
  LIMIT max_rows
$$""",
    """CREATE FUNCTION platform_admin_active(actor uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT coalesce((SELECT u.is_platform_admin AND u.is_active FROM users u WHERE u.id = actor), false)
$$""",
    # A release, guarded: the caller's tenant's held row of the kind it names, nothing else (never a write grant)
    """CREATE FUNCTION work_failure_release(released_kind text, item uuid) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  WITH gone AS (
    DELETE FROM work_failures f
     WHERE f.tenant_id = app_tenant_id() AND f.kind = released_kind AND f.item_id = item AND f.held_at IS NOT NULL
    RETURNING 1
  )
  SELECT EXISTS (SELECT 1 FROM gone)
$$""",
    # In bulk (the owner's ruling on the M3 checkpoint): the caller's tenant's held rows of one kind, held before a
    # time, counted, then released oldest first, 1,000 at most a call
    """CREATE FUNCTION work_failures_held_count(held_kind text, held_before timestamptz) RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT count(*)::integer FROM work_failures f
  WHERE f.tenant_id = app_tenant_id() AND f.kind = held_kind AND f.held_at IS NOT NULL AND f.held_at < held_before
$$""",
    """CREATE FUNCTION work_failures_release_many(held_kind text, held_before timestamptz, max_rows integer)
RETURNS TABLE (item_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  WITH gone AS (
    DELETE FROM work_failures f WHERE (f.tenant_id, f.item_id, f.kind) IN (
      SELECT w.tenant_id, w.item_id, w.kind FROM work_failures w
      WHERE w.tenant_id = app_tenant_id() AND w.kind = held_kind AND w.held_at IS NOT NULL AND w.held_at < held_before
      ORDER BY w.held_at, w.item_id
      LIMIT least(max_rows, 1000))
    RETURNING f.item_id, f.held_at
  )
  SELECT gone.item_id FROM gone ORDER BY gone.held_at, gone.item_id
$$""",
    """CREATE FUNCTION work_failures_held(max_rows integer)
RETURNS TABLE (tenant_id uuid, kind text, item_id uuid, errors integer, last_error text, held_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT f.tenant_id, f.kind::text, f.item_id, f.errors, f.last_error::text, f.held_at FROM work_failures f
  WHERE f.held_at IS NOT NULL
  ORDER BY f.held_at, f.tenant_id, f.item_id, f.kind
  LIMIT max_rows
$$""",
    """CREATE FUNCTION recovery_items_listed(max_rows integer)
RETURNS TABLE (tenant_id uuid, reason text, item_id uuid, since timestamptz, last_seen_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  SELECT r.tenant_id, r.reason::text, r.item_id, r.since, r.last_seen_at FROM recovery_items r
  ORDER BY r.since, r.tenant_id, r.item_id, r.reason
  LIMIT max_rows
$$""",
    *(f"REVOKE ALL ON FUNCTION {f} FROM PUBLIC" for f in ("pending_commands(integer)", "platform_admin_active(uuid)",
                                                           "work_failure_release(text, uuid)",
                                                           "work_failures_held_count(text, timestamptz)",
                                                           "work_failures_release_many(text, timestamptz, integer)",
                                                           "work_failures_held(integer)",
                                                           "recovery_items_listed(integer)")),
    "GRANT EXECUTE ON FUNCTION pending_commands(integer), platform_admin_active(uuid) TO dewpoint_dispatch",
    "GRANT EXECUTE ON FUNCTION work_failure_release(text, uuid), work_failures_held(integer), "
    "work_failures_held_count(text, timestamptz), work_failures_release_many(text, timestamptz, integer), "
    "recovery_items_listed(integer) TO dewpoint_api",
    "GRANT SELECT ON recovery_items TO dewpoint_api",
    f"GRANT SELECT (id, {OPERATOR_COLUMNS}, status, outcome, requested_at, decided_at) ON operator_commands "
    "TO dewpoint_api",
    f"GRANT INSERT ({OPERATOR_COLUMNS}, evidence) ON operator_commands TO dewpoint_api",
]  # fmt: skip
# An item's count, hold or recovery reason goes once the item settles (the owner's ruling on the M3 checkpoint): its
# row stays only while the item is in the state its kind of work, or its recovery, acts on (as each candidate function
# picks it), a bounded number a call, each table's
_LIVE_WORK = """CASE w.kind
          WHEN 'dispatch' THEN EXISTS (SELECT 1 FROM run_requests q WHERE q.id = w.item_id AND q.tenant_id = w.tenant_id
                                         AND q.status = 'queued')
          WHEN 'reconcile_starting' THEN EXISTS (SELECT 1 FROM run_requests q WHERE q.id = w.item_id
                                                   AND q.tenant_id = w.tenant_id AND q.status = 'starting')
          WHEN 'reconcile_open' THEN EXISTS (SELECT 1 FROM run_requests q JOIN runs u ON u.id = q.id
                                               WHERE q.id = w.item_id AND q.tenant_id = w.tenant_id
                                                 AND q.status = 'started' AND u.status = 'running')
          WHEN 'reconcile_slot' THEN EXISTS (SELECT 1 FROM run_slots t WHERE t.run_id = w.item_id
                                               AND t.tenant_id = w.tenant_id)
          WHEN 'cancel' THEN EXISTS (SELECT 1 FROM run_requests q JOIN runs u ON u.id = q.id
                                       WHERE q.id = w.item_id AND q.tenant_id = w.tenant_id AND q.status = 'started'
                                         AND q.cancel_requested_at IS NOT NULL AND q.cancel_sent_at IS NULL
                                         AND u.status = 'running')
          WHEN 'match' THEN EXISTS (SELECT 1 FROM inbound_events e WHERE e.id = w.item_id AND e.tenant_id = w.tenant_id
                                      AND e.status = 'pending')
          WHEN 'subrun' THEN EXISTS (SELECT 1 FROM runs u WHERE u.id = w.item_id AND u.tenant_id = w.tenant_id
                                       AND u.status = 'running')
          ELSE true END"""
_LIVE_REASON = """CASE i.reason
          WHEN 'run_history_missing' THEN EXISTS (SELECT 1 FROM runs u WHERE u.id = i.item_id
                                                    AND u.tenant_id = i.tenant_id AND u.status = 'running')
          WHEN 'subrun_history_missing' THEN EXISTS (SELECT 1 FROM runs u WHERE u.id = i.item_id
                                                       AND u.tenant_id = i.tenant_id AND u.status = 'running')
          WHEN 'slot_history_missing' THEN EXISTS (SELECT 1 FROM run_slots t WHERE t.run_id = i.item_id
                                                     AND t.tenant_id = i.tenant_id)
          ELSE EXISTS (SELECT 1 FROM run_requests q WHERE q.id = i.item_id AND q.tenant_id = i.tenant_id
                         AND q.status = 'starting') END"""
SETTLED = [
    f"""CREATE FUNCTION work_settled_clear(max_rows integer) RETURNS integer
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
  WITH failures AS (
    DELETE FROM work_failures f WHERE (f.tenant_id, f.item_id, f.kind) IN (
      SELECT w.tenant_id, w.item_id, w.kind FROM work_failures w WHERE NOT ({_LIVE_WORK}) LIMIT max_rows)
    RETURNING 1
  ), reasons AS (
    DELETE FROM recovery_items r WHERE (r.tenant_id, r.item_id, r.reason) IN (
      SELECT i.tenant_id, i.item_id, i.reason FROM recovery_items i WHERE NOT ({_LIVE_REASON}) LIMIT max_rows)
    RETURNING 1
  )
  SELECT ((SELECT count(*) FROM failures) + (SELECT count(*) FROM reasons))::integer
$$""",
    "REVOKE ALL ON FUNCTION work_settled_clear(integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION work_settled_clear(integer) TO dewpoint_dispatch",
]
ACCESS = [
    "GRANT SELECT, INSERT, UPDATE, DELETE ON work_failures, recovery_items TO dewpoint_dispatch",
    "GRANT SELECT ON operator_commands TO dewpoint_dispatch",
    "GRANT UPDATE (status, outcome, decided_at) ON operator_commands TO dewpoint_dispatch",
    "GRANT SELECT (tenant_id, kind, item_id) ON work_failures TO dewpoint_retention",
    "GRANT SELECT (tenant_id, reason, item_id) ON recovery_items TO dewpoint_retention",
    "GRANT SELECT (id, tenant_id, item_id) ON operator_commands TO dewpoint_retention",
    "GRANT DELETE ON work_failures, recovery_items, operator_commands TO dewpoint_retention",
]


def upgrade() -> None:
    with online() as conn:
        step(conn, "0050 failures, recovery items and commands", *_tables(),
             done=exists("relation", "operator_commands"))  # fmt: skip
        for table in TABLES:
            step(conn, f"0050 {table} fenced", _fence(table), done=exists("trigger", f"{table}_fence", table))
        step(conn, "0050 event_candidates past the busy", *ungranted(*CURSOR),
             done=exists("function", "event_candidates(integer, uuid[], uuid[])"))  # fmt: skip
        step(conn, "0050 candidates skip failing items", *SKIPPING, *ungranted(*CLEAR),
             done=exists("function", "recovery_items_clear(text[], uuid[], uuid[])"))  # fmt: skip
        step(conn, "0050 the operator's functions", *ungranted(*OPERATOR),
             done=exists("function", "recovery_items_listed(integer)"))  # fmt: skip
        step(conn, "0050 settled entries cleared", *ungranted(*SETTLED),
             done=exists("function", "work_settled_clear(integer)"))  # fmt: skip
        step(conn, "0050 a tenant's next due request", *ungranted(*NEXT),
             done=exists("function", "dispatch_next(uuid[])"))  # fmt: skip
        added = f"ALTER TABLE platform_settings {', '.join(f'ADD COLUMN {c}' for c in CAPACITY)}"
        step(conn, "0050 the ingress capacity", added, *ungranted(*SET_CAPACITY),
             done=exists("column", "ingress_queue_wait_s", "platform_settings"))  # fmt: skip
        step(conn, "0050 event rates from the ingress capacity", _rated())
        index(conn, "0050 run_requests_queued_webhook", QUEUED_INDEX)
        step(conn, "0050 grants", *grants(*CURSOR), *grants(*CLEAR), *grants(*OPERATOR), *grants(*SETTLED),
             *grants(*NEXT), *grants(*SET_CAPACITY), *ACCESS)  # fmt: skip


def downgrade() -> None:
    for prior in (DISPATCH_0049, CANCEL_0049, RECONCILE_0049, ORPHANS_0049):
        op.execute(prior.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    for table in ("work_failures", "recovery_items"):
        op.execute(f"DROP FUNCTION {table}_clear(text[], uuid[], uuid[])")
    op.execute("DROP FUNCTION work_settled_clear(integer)")
    op.execute("DROP FUNCTION dispatch_next(uuid[])")
    op.execute(_recorder_0039())
    op.execute("DROP INDEX run_requests_queued_webhook")
    op.execute("DROP FUNCTION set_ingress_capacity(jsonb)")
    op.execute("ALTER TABLE platform_settings DROP COLUMN ingress_starts_per_s, DROP COLUMN ingress_headroom, "
               "DROP COLUMN ingress_queue_wait_s")  # fmt: skip
    for function in ("work_failures_held_count(text, timestamptz)", "work_failures_release_many(text, timestamptz, integer)",
                     "pending_commands(integer)", "platform_admin_active(uuid)", "work_failure_release(text, uuid)",
                     "work_failures_held(integer)", "recovery_items_listed(integer)"):  # fmt: skip
        op.execute(f"DROP FUNCTION {function}")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION event_candidates(integer, uuid[], uuid[])")
