# SPDX-License-Identifier: Apache-2.0
"""2b-4b M3's hardening (a provisional slot, on the lineage-reconciliation list with 0049).

- **Matching pages past a busy prefix** (D9, the owner's correction): `event_candidates` takes a keyset cursor,
  `(rank, received_at, event id)` of the last candidate a pass visited, and returns `rank` and `received_at` too, so
  each pass goes on from where the last stopped and wraps around once a pick comes back short: an event behind any
  number of busy ones is reached within a bounded number of passes. The one-argument form stays for a dispatcher of an
  earlier build during a rollout. Still ids and ordering only, locking nothing.

Online (D15), in steps; grants last."""

from alembic import op

from migrations.online import exists, grants, online, step, ungranted

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

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
  ) ranked
  WHERE after_rank IS NULL OR (ranked.rank, ranked.received_at, ranked.id) > (after_rank, after_received, after_event)
  ORDER BY ranked.rank, ranked.received_at, ranked.id
  LIMIT max_events
$$""",
    "REVOKE ALL ON FUNCTION event_candidates(integer, bigint, timestamptz, uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION event_candidates(integer, bigint, timestamptz, uuid) TO dewpoint_dispatch",
]


def upgrade() -> None:
    with online() as conn:
        step(conn, "0050 event_candidates cursor", *ungranted(*CURSOR),
             done=exists("function", "event_candidates(integer, bigint, timestamptz, uuid)"))  # fmt: skip
        step(conn, "0050 grants", *grants(*CURSOR))


def downgrade() -> None:
    op.execute("DROP FUNCTION event_candidates(integer, bigint, timestamptz, uuid)")
