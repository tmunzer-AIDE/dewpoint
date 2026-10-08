# SPDX-License-Identifier: Apache-2.0
"""2b-4b M3's hardening (a provisional slot, on the lineage-reconciliation list with 0049).

- **Matching pages past a busy prefix** (D9, the owner's correction): `event_candidates` takes a keyset cursor,
  `(rank, received_at, event id)` of the last candidate a pass visited, and returns `rank` and `received_at` too, so
  each pass goes on from where the last stopped and wraps around once a pick comes back short: an event behind any
  number of busy ones is reached within a bounded number of passes. The one-argument form stays for a dispatcher of an
  earlier build during a rollout. Still ids and ordering only, locking nothing.
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

import uuid
from collections.abc import Callable

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
    """CREATE FUNCTION event_candidates(max_events integer, after_rank bigint, after_received timestamptz,
                                 after_event uuid)
RETURNS TABLE (tenant_id uuid, event_id uuid, endpoint_id uuid, rank bigint, received_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT ranked.tenant_id, ranked.id, ranked.endpoint_id, ranked.rank, ranked.received_at FROM (
    SELECT e.tenant_id, e.id, e.endpoint_id, e.received_at,
           row_number() OVER (PARTITION BY e.tenant_id ORDER BY e.received_at, e.id) AS rank
      FROM public.inbound_events e
     WHERE e.status = 'pending' AND (e.next_attempt_at IS NULL OR e.next_attempt_at <= now())
       AND MATCH_SKIP
  ) ranked
  WHERE after_rank IS NULL OR (ranked.rank, ranked.received_at, ranked.id) > (after_rank, after_received, after_event)
  ORDER BY ranked.rank, ranked.received_at, ranked.id
  LIMIT max_events
$$""",
    "REVOKE ALL ON FUNCTION event_candidates(integer, bigint, timestamptz, uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION event_candidates(integer, bigint, timestamptz, uuid) TO dewpoint_dispatch",
]
CURSOR[0] = CURSOR[0].replace("MATCH_SKIP", _unless("'match'", "e.tenant_id", "e.id"))


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


def _secured(table: str) -> list[str]:
    """Its tenant's, as it's made: the dispatcher and the retention process within their scope (D15: in its step)."""
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {table}_scope ON {table} TO dewpoint_dispatch, dewpoint_retention "
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
        *_secured("recovery_items"),
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
        *_secured("operator_commands"),
    ]


def _fence(table: str) -> str:
    return f"CREATE TRIGGER {table}_fence BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION tenant_insert_fence()"


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
        step(conn, "0050 event_candidates cursor", *ungranted(*CURSOR),
             done=exists("function", "event_candidates(integer, bigint, timestamptz, uuid)"))  # fmt: skip
        step(conn, "0050 candidates skip failing items", *SKIPPING, *ungranted(*CLEAR),
             done=exists("function", "recovery_items_clear(text[], uuid[], uuid[])"))  # fmt: skip
        step(conn, "0050 grants", *grants(*CURSOR), *grants(*CLEAR), *ACCESS)


def downgrade() -> None:
    for prior in (DISPATCH_0049, CANCEL_0049, RECONCILE_0049, ORPHANS_0049):
        op.execute(prior.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    for table in ("work_failures", "recovery_items"):
        op.execute(f"DROP FUNCTION {table}_clear(text[], uuid[], uuid[])")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION event_candidates(integer, bigint, timestamptz, uuid)")
