# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4 recovery, gate D (the owner's ruling, item 3): `erasures_held` counts stopped erasures too.

`unresolved_sends_counts(token)` (0058) counted the incomplete erasures of tenants a blocker names, leaving out the
stopped ones. Stopping an erasure removes neither its blocker nor the hold (`erasure_unresolved`, 0061, counts every
blocker), so every incomplete one is counted, stopped or not. Replaced in place: the same signature, owner and grant;
nothing else changes.

One transaction, Alembic's own, each lock wait bounded (5 s): one function replaced, no table changed. It keeps no
row, so its downgrade, which restores 0058's text exactly, refuses nothing."""

from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
COUNTS = """CREATE OR REPLACE FUNCTION unresolved_sends_counts(token text)
RETURNS TABLE (state text, requests bigint, open_sends bigint, oldest timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
#variable_conflict use_column
BEGIN
  PERFORM admin_session($1);
  RETURN QUERY
  SELECT k.state, count(b.request_id), coalesce(sum(o.open), 0)::bigint, min(b.first_at)
    FROM (VALUES ('pending'), ('unresolved'), ('identified'), ('deleted_open')) k(state)
    LEFT JOIN unresolved_sends b ON b.state = k.state
    LEFT JOIN LATERAL (SELECT count(*) AS open FROM start_sends x
                        WHERE x.request_id = b.request_id AND x.answer IS NULL) o ON true
   GROUP BY k.state
  UNION ALL
  SELECT 'erasures_held', count(*), NULL::bigint, min(e.requested_at) FROM tenant_erasures e
   WHERE e.completed_at IS NULL
     AND EXISTS (SELECT 1 FROM unresolved_sends b WHERE b.tenant_id = e.tenant_id);
END $$"""
COUNTS_0058 = """CREATE OR REPLACE FUNCTION unresolved_sends_counts(token text)
RETURNS TABLE (state text, requests bigint, open_sends bigint, oldest timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp SET row_security = off AS $$
#variable_conflict use_column
BEGIN
  PERFORM admin_session($1);
  RETURN QUERY
  SELECT k.state, count(b.request_id), coalesce(sum(o.open), 0)::bigint, min(b.first_at)
    FROM (VALUES ('pending'), ('unresolved'), ('identified'), ('deleted_open')) k(state)
    LEFT JOIN unresolved_sends b ON b.state = k.state
    LEFT JOIN LATERAL (SELECT count(*) AS open FROM start_sends x
                        WHERE x.request_id = b.request_id AND x.answer IS NULL) o ON true
   GROUP BY k.state
  UNION ALL
  SELECT 'erasures_held', count(*), NULL::bigint, min(e.requested_at) FROM tenant_erasures e
   WHERE e.completed_at IS NULL AND e.stopped_at IS NULL
     AND EXISTS (SELECT 1 FROM unresolved_sends b WHERE b.tenant_id = e.tenant_id);
END $$"""


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute(COUNTS)


def downgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute(COUNTS_0058)
