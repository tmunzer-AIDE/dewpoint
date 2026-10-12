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
  `record_inbound_events()` (derived from 0039's text, as 0039 derives it from 0032's) holds an endpoint's events to
  their product divided by its enabled bindings, a lower configured rate staying.
- **The deployment's ingress budget** (the owner's ruling on the M3 checkpoint 4): one limit on the webhook work
  outstanding, the three values' product (at least 40; 50,000, development-only, until they're all set). A pending
  event counts its credit (its endpoint's enabled bindings when accepted), a webhook request queued or starting 1.
  `record_inbound_events()` admits a delivery under the budget's row within ingress's room (the limit but what's kept
  for top-ups), each tenant within its share and all of them keeping one share free for a tenant yet to come (a single
  event excepted, as an event can't be split); else `backlog_full`, nothing stored, or `over_limit` for one that could
  never fit. A match's requests take its event's credit, past it only within the limit. Deferred triggers count every
  request inserted and release every way out, whoever writes the row, and refuse a commit that adds past the limit
  (the ruling on the M3 checkpoint 5). A capacity change never takes the limit below the work outstanding.
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

from migrations.online import exists, grants, online, step, ungranted

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
    v_outstanding bigint;
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
    -- Never a limit below the work already outstanding (the owner's ruling on the M3 checkpoint 5): under the
    -- budget's row, so an admission in flight is waited for and counted, and none starts meanwhile
    SELECT outstanding INTO v_outstanding FROM ingress_budget WHERE id = 1 FOR UPDATE;
    UPDATE platform_settings SET ingress_starts_per_s = p.ingress_starts_per_s, ingress_headroom = p.ingress_headroom,
        ingress_queue_wait_s = p.ingress_queue_wait_s WHERE id = 1;
    IF v_outstanding > ingress_limit() THEN
        RAISE EXCEPTION 'the ingress limit would be below the work outstanding' USING ERRCODE = 'DPC02';
    END IF;
    RETURN jsonb_build_object('before', v_before, 'after', jsonb_build_object(
        'starts_per_s', p.ingress_starts_per_s, 'headroom', p.ingress_headroom, 'queue_wait_s', p.ingress_queue_wait_s));
END
$$""",
    "REVOKE ALL ON FUNCTION set_ingress_capacity(jsonb) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION set_ingress_capacity(jsonb) TO dewpoint_api",
]


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


RATES = {  # 0039's text: what it reads, how it refills and waits, and what it admits (the owner's rulings on the M3
    # checkpoints 2 and 4): an endpoint's event rate derived once the capacity's set; every delivery within the budget
    "    v_wait double precision;\n": "    v_wait double precision;\n    v_budget double precision;\n"
    "    v_fanout integer;\n    v_event_rate double precision;\n    v_weight bigint;\n    v_short bigint;\n",
    "    SELECT environment INTO v_environment FROM public.platform_settings WHERE id = 1;\n":
    "    SELECT environment, ingress_starts_per_s * ingress_headroom INTO v_environment, v_budget\n"
    "      FROM public.platform_settings WHERE id = 1;\n",
    "    -- The rate limits, by the clock as it is now,":
    "    -- An event becomes a request for each of its endpoint's enabled bindings: its credit, and the endpoint's\n"
    "    -- event rate once the deployment's capacity is set (the headroom's share of its measured starts divided by\n"
    "    -- them; a rate configured lower stays)\n"
    "    SELECT greatest(count(*), 1) INTO v_fanout FROM public.trigger_bindings b\n"
    "     WHERE b.tenant_id = v_tenant AND b.endpoint_id = p_endpoint AND b.enabled;\n"
    "    v_event_rate := e.event_per_s;\n"
    "    IF v_budget IS NOT NULL THEN\n"
    "        v_event_rate := least(v_event_rate, v_budget / v_fanout);\n"
    "    END IF;\n\n"
    "    -- The rate limits, by the clock as it is now,",
    "e.event_tokens + e.event_per_s * extract": "e.event_tokens + v_event_rate * extract",
    "(v_events - e.event_tokens) / e.event_per_s,": "(v_events - e.event_tokens) / v_event_rate,",
    "    INSERT INTO public.inbound_events (id, tenant_id, endpoint_id, dedupe_key, content_digest, key_version, sealed, "
    "size_bytes)\n":
    "    -- The deployment's budget: the new events' credit admitted, or nothing stored (the owner's ruling on the M3\n"
    "    -- checkpoint 4)\n"
    "    IF cardinality(v_new) > 0 THEN\n"
    "        v_weight := cardinality(v_new)::bigint * v_fanout;\n"
    "        v_short := public.ingress_admit(v_tenant, v_weight, cardinality(v_new));\n"
    "        IF v_short < 0 THEN  -- it could never fit: no retry helps it\n"
    "            RETURN jsonb_build_object('outcome', 'over_limit');\n"
    "        END IF;\n"
    "        IF v_short > 0 THEN\n"
    "            RETURN jsonb_build_object('outcome', 'backlog_full', 'retry_after', CASE WHEN v_budget IS NULL THEN 30\n"
    "                ELSE greatest(1, least(60, ceil(v_short / v_budget)))::integer END);\n"
    "        END IF;\n"
    "    END IF;\n"
    "    INSERT INTO public.inbound_events (id, tenant_id, endpoint_id, dedupe_key, content_digest, key_version, sealed, "
    "size_bytes, credit)\n",
    "octet_length(p_sealed[k])\n      FROM unnest(v_new) AS k;": "octet_length(p_sealed[k]), v_fanout\n      FROM unnest(v_new) AS k;",
}  # fmt: skip


def _rated() -> str:
    """0039's `record_inbound_events()`, its event rates derived from the ingress capacity."""
    recorder = _recorder_0039()
    for anchor, replaced in RATES.items():
        if recorder.count(anchor) != 1:
            raise RuntimeError(f"0039's record_inbound_events() isn't the text this migration changes: {anchor!r}")
        recorder = recorder.replace(anchor, replaced)
    return recorder


# The deployment's ingress budget (the owner's ruling on the M3 checkpoint 4): one row, every tenant's outstanding work
# and how many tenants have any; each tenant's on its own row, written only under the budget's (so a transaction holding
# the budget waits on no tenant's row); each event's credit, its fan-out when accepted.
#
# The lock order: whatever a transaction holds already (an endpoint's row, a tenant's counter row, a request's), then
# the budget's row, then the tenants' budget rows. Ingress's admission and a match's check take the budget when they
# ask; what a request adds and every release wait for their transaction's commit (deferred triggers, counting whoever
# writes the row), so a transaction releasing many tenants' work (a plugin's retirement cancelling their requests,
# say) takes the budget last, its other rows all held already.
BUDGET = [
    lambda: op.create_table(
        "ingress_budget",
        sa.Column("id", sa.SmallInteger, primary_key=True),
        sa.Column("outstanding", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("active", sa.Integer, nullable=False, server_default="0"),
        sa.CheckConstraint("id = 1", name="ingress_budget_one"),
        sa.CheckConstraint("outstanding >= 0 AND active >= 0", name="ingress_budget_counts"),
    ),
    "INSERT INTO ingress_budget (id) VALUES (1)",
    lambda: op.create_table(
        "ingress_outstanding",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), primary_key=True),  # its tenant's while it has one
        sa.Column("outstanding", sa.BigInteger, nullable=False, server_default="0"),
        sa.CheckConstraint("outstanding >= 0", name="ingress_outstanding_counts"),
    ),
    "ALTER TABLE ingress_outstanding ENABLE ROW LEVEL SECURITY",  # no role but its functions' owner reads it
]
CREDIT = "ALTER TABLE inbound_events ADD COLUMN credit smallint"  # none before: what they owe is nothing
DEV_LIMIT = 50_000  # the deployment's outstanding work at most, until its capacity's whole: development-only
MAX_BINDINGS = 20  # an endpoint's most (core/ingress/filters.py), as of this migration
DEFINER = "SECURITY DEFINER SET search_path = public, pg_temp"
CREDITED = [
    f"""CREATE FUNCTION ingress_limit() RETURNS bigint LANGUAGE sql STABLE {DEFINER} AS $$
  SELECT CASE WHEN p.ingress_starts_per_s IS NULL OR p.ingress_headroom IS NULL OR p.ingress_queue_wait_s IS NULL
              THEN {DEV_LIMIT}::bigint
              ELSE greatest({2 * MAX_BINDINGS}, floor(p.ingress_starts_per_s * p.ingress_headroom
                                                      * p.ingress_queue_wait_s))::bigint END
    FROM platform_settings p WHERE p.id = 1
$$""",
    # What ingress may fill: the limit but what's kept for top-ups (an event's most bindings but the one its credit
    # holds), so an event whose bindings grew since it was accepted is never starved behind deliveries (the fresh
    # review 5's I2); at least an event's most bindings, with the limit's floor
    f"""CREATE FUNCTION ingress_room() RETURNS bigint LANGUAGE sql STABLE {DEFINER} AS $$
  SELECT ingress_limit() - {MAX_BINDINGS - 1}
$$""",
    # The count as the transaction first touched it (a transaction-local setting): the bound refuses a commit only past
    # both the limit and where it started (the fresh review 6's M1). The caller holds the budget's row
    f"""CREATE FUNCTION ingress_started() RETURNS void LANGUAGE plpgsql {DEFINER} AS $$
BEGIN
    IF coalesce(current_setting('dewpoint.ingress_before', true), '') = '' THEN
        PERFORM set_config('dewpoint.ingress_before', (SELECT outstanding FROM ingress_budget WHERE id = 1)::text,
                           true);
    END IF;
END
$$""",
    # A tenant's outstanding work moved by `delta`, and the deployment's with it, never below nothing; a tenant whose
    # row is gone (its counters erased took what it held with them) moves nothing
    f"""CREATE FUNCTION ingress_credit(p_tenant uuid, p_delta bigint) RETURNS void LANGUAGE plpgsql {DEFINER} AS $$
DECLARE
    v_was bigint;
    v_now bigint;
BEGIN
    IF p_delta = 0 THEN
        RETURN;
    END IF;
    PERFORM 1 FROM ingress_budget WHERE id = 1 FOR UPDATE;
    IF NOT FOUND THEN  -- the migration's row, never deleted: counting nothing is never right
        RAISE EXCEPTION 'ingress_budget_missing' USING ERRCODE = 'DPB01';
    END IF;
    PERFORM ingress_started();
    SELECT outstanding INTO v_was FROM ingress_outstanding WHERE tenant_id = p_tenant;
    IF NOT FOUND THEN
        IF p_delta < 0 THEN
            RETURN;
        END IF;
        v_was := 0;
        INSERT INTO ingress_outstanding (tenant_id, outstanding) VALUES (p_tenant, p_delta);
    ELSE
        UPDATE ingress_outstanding SET outstanding = greatest(v_was + p_delta, 0) WHERE tenant_id = p_tenant;
    END IF;
    v_now := greatest(v_was + p_delta, 0);
    UPDATE ingress_budget SET outstanding = greatest(outstanding + (v_now - v_was), 0),
        active = greatest(active + CASE WHEN v_was = 0 AND v_now > 0 THEN 1 WHEN v_was > 0 AND v_now = 0 THEN -1
                                        ELSE 0 END, 0)
     WHERE id = 1;
END
$$""",
    # `weight` (`events` events' credit) more for a tenant, under the budget's row, within ingress's room, and always
    # keeping one share free for a tenant yet to come (the owner's ruling on the M3 checkpoint 5; the fresh review 6's
    # I2), the share being the room over the tenants with work outstanding once it's admitted and one more:
    # - the tenant holds at most its share, but a single event may take more when it holds nothing (an event can't be
    #   split: one of the most bindings stays admissible at the least limit, the review's I1);
    # - all of them hold at most the room but that share, but a single event may come into a deployment holding
    #   nothing else.
    # 0 when admitted; how much past; or -1 when it could never fit, even alone in an otherwise empty deployment: more
    # than one event worth more than half the room
    f"""CREATE FUNCTION ingress_admit(p_tenant uuid, p_weight bigint, p_events integer) RETURNS bigint
LANGUAGE plpgsql {DEFINER} AS $$
DECLARE
    v_mine bigint;
    v_all bigint;
    v_active integer;
    v_room bigint;
    v_share bigint;
    v_single boolean := p_events = 1;
BEGIN
    SELECT outstanding, active INTO v_all, v_active FROM ingress_budget WHERE id = 1 FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ingress_budget_missing' USING ERRCODE = 'DPB01';
    END IF;
    SELECT coalesce((SELECT outstanding FROM ingress_outstanding WHERE tenant_id = p_tenant), 0) INTO v_mine;
    v_room := ingress_room();
    IF NOT v_single AND p_weight > floor(v_room / 2.0) THEN
        RETURN -1;
    END IF;
    IF v_all + p_weight > v_room THEN
        RETURN v_all + p_weight - v_room;
    END IF;
    v_share := floor(v_room::numeric / (v_active + CASE WHEN v_mine = 0 THEN 1 ELSE 0 END + 1));
    IF v_mine + p_weight > v_share AND NOT (v_mine = 0 AND v_single) THEN
        RETURN v_mine + p_weight - v_share;
    END IF;
    IF v_all + p_weight > v_room - v_share AND NOT (v_all = 0 AND v_single) THEN
        RETURN v_all + p_weight - (v_room - v_share);
    END IF;
    PERFORM ingress_credit(p_tenant, p_weight);
    RETURN 0;
END
$$""",
    # Whether a matched event's new queued requests fit: each is counted as it's inserted and the event's credit
    # released, both at the commit; within that credit they always do, past it (bindings added since it was accepted)
    # only within the limit's room, the budget's row then held to the commit
    f"""CREATE FUNCTION ingress_matched(p_credit bigint, p_requests bigint) RETURNS boolean
LANGUAGE plpgsql {DEFINER} AS $$
DECLARE
    v_all bigint;
BEGIN
    IF p_requests <= p_credit THEN
        RETURN true;
    END IF;
    SELECT outstanding INTO v_all FROM ingress_budget WHERE id = 1 FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ingress_budget_missing' USING ERRCODE = 'DPB01';
    END IF;
    RETURN v_all + (p_requests - p_credit) <= ingress_limit();
END
$$""",
    f"""CREATE FUNCTION ingress_budget_drift() RETURNS TABLE (counted bigint, actual bigint)
LANGUAGE sql STABLE {DEFINER} AS $$
  SELECT (SELECT b.outstanding FROM ingress_budget b WHERE b.id = 1),
         (SELECT coalesce(sum(e.credit), 0) FROM inbound_events e WHERE e.status = 'pending')::bigint
         + (SELECT count(*) FROM run_requests r WHERE r.source = 'webhook' AND r.status IN ('queued', 'starting'))
$$""",
    "REVOKE ALL ON FUNCTION ingress_limit(), ingress_room(), ingress_started(), ingress_credit(uuid, bigint), "
    "ingress_admit(uuid, bigint, integer), "
    "ingress_matched(bigint, bigint), ingress_budget_drift() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION ingress_matched(bigint, bigint), ingress_budget_drift() TO dewpoint_dispatch",
    "GRANT EXECUTE ON FUNCTION ingress_limit() TO dewpoint_api",  # the platform admin's API shows it
]
HOLDING = "('queued', 'starting')"
RELEASES = [  # every way out of the budget (the owner's ruling on the M3 checkpoint 4), by trigger, at the commit
    f"""CREATE FUNCTION ingress_event_settled() RETURNS trigger LANGUAGE plpgsql {DEFINER} AS $$
BEGIN
    PERFORM ingress_credit(OLD.tenant_id, -coalesce(OLD.credit, 0));
    RETURN NULL;
END
$$""",
    f"""CREATE FUNCTION ingress_request_queued() RETURNS trigger LANGUAGE plpgsql {DEFINER} AS $$
BEGIN
    PERFORM ingress_credit(NEW.tenant_id, 1);
    RETURN NULL;
END
$$""",
    f"""CREATE FUNCTION ingress_request_settled() RETURNS trigger LANGUAGE plpgsql {DEFINER} AS $$
BEGIN
    PERFORM ingress_credit(OLD.tenant_id, -1);
    RETURN NULL;
END
$$""",
    f"""CREATE FUNCTION ingress_tenant_gone() RETURNS trigger LANGUAGE plpgsql {DEFINER} AS $$
DECLARE
    v_was bigint;
BEGIN
    PERFORM 1 FROM ingress_budget WHERE id = 1 FOR UPDATE;
    PERFORM ingress_started();
    DELETE FROM ingress_outstanding WHERE tenant_id = OLD.tenant_id RETURNING outstanding INTO v_was;
    IF FOUND THEN
        UPDATE ingress_budget SET outstanding = greatest(outstanding - v_was, 0),
            active = greatest(active - CASE WHEN v_was > 0 THEN 1 ELSE 0 END, 0) WHERE id = 1;
    END IF;
    RETURN NULL;
END
$$""",
    "REVOKE ALL ON FUNCTION ingress_event_settled(), ingress_request_queued(), ingress_request_settled(), "
    "ingress_tenant_gone() FROM PUBLIC",
    "CREATE TRIGGER ingress_outstanding_fence BEFORE INSERT ON ingress_outstanding FOR EACH ROW "
    "EXECUTE FUNCTION tenant_insert_fence()",
]
# Each table's triggers a step of its own (one table in use a step). A tenant's counters deleted first: the rows the
# last step counts don't exist yet, and an erasure deletes counters only once its tenant's requests are cancelled
GONE = [
    "CREATE CONSTRAINT TRIGGER tenant_event_counters_credit_gone AFTER DELETE ON tenant_event_counters "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ingress_tenant_gone()",
]
# No event before had a credit: nothing to count, their releases nothing until the recorder gives them one
SETTLED_EVENTS = [
    "CREATE CONSTRAINT TRIGGER inbound_events_credit_settled AFTER UPDATE OF status ON inbound_events "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (OLD.status = 'pending' AND NEW.status <> 'pending') "
    "EXECUTE FUNCTION ingress_event_settled()",
    "CREATE CONSTRAINT TRIGGER inbound_events_credit_deleted AFTER DELETE ON inbound_events "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (OLD.status = 'pending') EXECUTE FUNCTION ingress_event_settled()",
]
# The requests' triggers and what's outstanding already, counted in their transaction (their lock holds every write)
COUNTED = [
    "CREATE CONSTRAINT TRIGGER run_requests_credit_queued AFTER INSERT ON run_requests "
    f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.source = 'webhook' AND NEW.status IN {HOLDING}) "
    "EXECUTE FUNCTION ingress_request_queued()",
    "CREATE CONSTRAINT TRIGGER run_requests_credit_settled AFTER UPDATE OF status ON run_requests "
    f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (OLD.source = 'webhook' AND OLD.status IN {HOLDING} "
    f"AND NEW.status NOT IN {HOLDING}) EXECUTE FUNCTION ingress_request_settled()",
    "CREATE CONSTRAINT TRIGGER run_requests_credit_deleted AFTER DELETE ON run_requests "
    f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (OLD.source = 'webhook' AND OLD.status IN {HOLDING}) "
    "EXECUTE FUNCTION ingress_request_settled()",
    f"""INSERT INTO ingress_outstanding (tenant_id, outstanding)
  SELECT r.tenant_id, count(*) FROM run_requests r WHERE r.source = 'webhook' AND r.status IN {HOLDING}
   GROUP BY r.tenant_id""",
    """UPDATE ingress_budget SET outstanding = (SELECT coalesce(sum(outstanding), 0) FROM ingress_outstanding),
    active = (SELECT count(*) FROM ingress_outstanding WHERE outstanding > 0) WHERE id = 1""",
]
# The limit, whoever writes (the owner's ruling on the M3 checkpoint 5): a commit never leaves the budget past the limit
# and past where it started. A dispatcher still on the code before 0050 (an upgrade rolling out) queues an event's
# requests without asking; its match is refused at its commit, its event left pending. Checked as the transaction
# commits, after its other deferred work (each increment's check fires a round later, reading the row as it ends). A
# commit adding nothing net is never refused (the fresh review 6's M1), so above the limit (drifted, say) matching
# within credit and starts go on, and it drains
BOUNDED = [
    f"""CREATE FUNCTION ingress_budget_bounded() RETURNS trigger LANGUAGE plpgsql {DEFINER} AS $$
DECLARE
    v_now bigint := (SELECT outstanding FROM ingress_budget WHERE id = 1);
BEGIN
    IF v_now > ingress_limit()
       AND v_now > coalesce(nullif(current_setting('dewpoint.ingress_before', true), '')::bigint, 0) THEN
        RAISE EXCEPTION 'the ingress budget would pass its limit' USING ERRCODE = 'DPB02';
    END IF;
    RETURN NULL;
END
$$""",
    "REVOKE ALL ON FUNCTION ingress_budget_bounded() FROM PUBLIC",
    "CREATE CONSTRAINT TRIGGER ingress_budget_bounded AFTER UPDATE OF outstanding ON ingress_budget "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.outstanding > OLD.outstanding) "
    "EXECUTE FUNCTION ingress_budget_bounded()",
]
BUDGET_READ = [
    "GRANT SELECT ON ingress_budget TO dewpoint_api, dewpoint_dispatch",
    "GRANT SELECT (credit) ON inbound_events TO dewpoint_api",  # every column but its ciphertext (0034)
]


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
        step(conn, "0050 the ingress budget", *BUDGET, done=exists("relation", "ingress_budget"))
        step(conn, "0050 inbound_events.credit", CREDIT, done=exists("column", "credit", "inbound_events"))
        step(conn, "0050 the budget's functions", *ungranted(*CREDITED),
             done=exists("function", "ingress_budget_drift()"))  # fmt: skip
        step(conn, "0050 the budget's releases", *RELEASES,
             done=exists("trigger", "ingress_outstanding_fence", "ingress_outstanding"))  # fmt: skip
        step(conn, "0050 tenant_event_counters releases", *GONE,
             done=exists("trigger", "tenant_event_counters_credit_gone", "tenant_event_counters"))  # fmt: skip
        step(conn, "0050 inbound_events releases", *SETTLED_EVENTS,
             done=exists("trigger", "inbound_events_credit_deleted", "inbound_events"))  # fmt: skip
        step(conn, "0050 run_requests counted", *COUNTED,
             done=exists("trigger", "run_requests_credit_deleted", "run_requests"))  # fmt: skip
        step(
            conn,
            "0050 the budget's bound",
            *BOUNDED,
            done=exists("trigger", "ingress_budget_bounded", "ingress_budget"),
        )
        step(conn, "0050 event rates and admission from the ingress budget", _rated())
        step(conn, "0050 grants", *grants(*CURSOR), *grants(*CLEAR), *grants(*OPERATOR), *grants(*SETTLED),
             *grants(*NEXT), *grants(*SET_CAPACITY), *grants(*CREDITED), *BUDGET_READ, *ACCESS)  # fmt: skip


def downgrade() -> None:
    for prior in (DISPATCH_0049, CANCEL_0049, RECONCILE_0049, ORPHANS_0049):
        op.execute(prior.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    for table in ("work_failures", "recovery_items"):
        op.execute(f"DROP FUNCTION {table}_clear(text[], uuid[], uuid[])")
    op.execute("DROP FUNCTION work_settled_clear(integer)")
    op.execute("DROP FUNCTION dispatch_next(uuid[])")
    op.execute(_recorder_0039())
    for trigger, table in (("ingress_budget_bounded", "ingress_budget"),
                           ("inbound_events_credit_settled", "inbound_events"),
                           ("inbound_events_credit_deleted", "inbound_events"),
                           ("run_requests_credit_queued", "run_requests"),
                           ("run_requests_credit_settled", "run_requests"), ("run_requests_credit_deleted", "run_requests"),
                           ("tenant_event_counters_credit_gone", "tenant_event_counters")):  # fmt: skip
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    op.execute("DROP FUNCTION ingress_budget_bounded(), ingress_event_settled(), ingress_request_queued(), "
               "ingress_request_settled(), "
               "ingress_tenant_gone(), "
               "ingress_budget_drift(), ingress_matched(bigint, bigint), ingress_admit(uuid, bigint, integer), "
               "ingress_credit(uuid, bigint), ingress_started(), ingress_room(), ingress_limit()")  # fmt: skip
    op.execute("ALTER TABLE inbound_events DROP COLUMN credit")
    op.drop_table("ingress_outstanding")
    op.drop_table("ingress_budget")
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
