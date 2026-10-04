# SPDX-License-Identifier: Apache-2.0
"""What matching, cancelling and the recount need (engine 2b spec §8.3; "Functions and lock order" in the 2b-3b
outline): `event_candidates(n)`, the dispatcher's pick of pending events, ids only and locking nothing, fair across
tenants (every tenant's oldest due event before any tenant's second); `recount_candidates(n)`, the tenants whose
counters the leader recounts, each at most every 10 minutes, by `recounted_at`; the API's grants to cancel events
within its tenant and release their pending counters."""

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

EVENT_CANDIDATES = """
CREATE FUNCTION event_candidates(max_events integer)
RETURNS TABLE (tenant_id uuid, event_id uuid, endpoint_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT ranked.tenant_id, ranked.id, ranked.endpoint_id FROM (
    SELECT e.tenant_id, e.id, e.endpoint_id, e.received_at,
           row_number() OVER (PARTITION BY e.tenant_id ORDER BY e.received_at, e.id) AS rank
      FROM public.inbound_events e
     WHERE e.status = 'pending' AND (e.next_attempt_at IS NULL OR e.next_attempt_at <= now())
  ) ranked
  ORDER BY ranked.rank, ranked.received_at, ranked.id
  LIMIT max_events
$$"""

RECOUNT_CANDIDATES = """
CREATE FUNCTION recount_candidates(max_tenants integer)
RETURNS TABLE (tenant_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT c.tenant_id FROM public.tenant_event_counters c
   WHERE c.recounted_at IS NULL OR c.recounted_at <= now() - interval '10 minutes'
   ORDER BY c.recounted_at NULLS FIRST, c.tenant_id
   LIMIT max_tenants
$$"""

FUNCTIONS = ("event_candidates(integer)", "recount_candidates(integer)")


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_event_counters ADD COLUMN recounted_at timestamptz")
    for statement in (
        EVENT_CANDIDATES,
        RECOUNT_CANDIDATES,
        *(
            statement
            for function in FUNCTIONS
            for statement in (
                f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC",
                f"GRANT EXECUTE ON FUNCTION {function} TO dewpoint_dispatch",
            )
        ),
        "GRANT UPDATE (recounted_at) ON tenant_event_counters TO dewpoint_dispatch",
        # An admin's cancel (tenant.manage): the event's end, and the pending counters it releases.
        "GRANT UPDATE (status, reason, ended_at) ON inbound_events TO dewpoint_api",
        "GRANT UPDATE (pending_events, pending_bytes) ON webhook_endpoints TO dewpoint_api",
        "GRANT UPDATE (pending_events, pending_bytes) ON tenant_event_counters TO dewpoint_api",
    ):
        op.execute(statement)


def downgrade() -> None:
    for statement in (
        "REVOKE UPDATE (pending_events, pending_bytes) ON tenant_event_counters FROM dewpoint_api",
        "REVOKE UPDATE (pending_events, pending_bytes) ON webhook_endpoints FROM dewpoint_api",
        "REVOKE UPDATE (status, reason, ended_at) ON inbound_events FROM dewpoint_api",
        "REVOKE UPDATE (recounted_at) ON tenant_event_counters FROM dewpoint_dispatch",
        *(f"DROP FUNCTION {function}" for function in FUNCTIONS),
        "ALTER TABLE tenant_event_counters DROP COLUMN recounted_at",
    ):
        op.execute(statement)
