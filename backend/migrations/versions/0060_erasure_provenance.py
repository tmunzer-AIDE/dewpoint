# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4 recovery, task 11: each known execution's provenance, and the erasure's new record (design revision 5 §3
and §5, revision 6 §4 and §5).

- `tenant_erasure_known.provenance`, written explicitly for every execution row, never for a schedule's: `gone` (shown,
  deleted, read back), `run_not_found` (an exact run whose describe answered NOT_FOUND before the erasure showed it),
  `absent` (an id alone, never shown), `retained_out` (task 15), `never_created` (a removed blocker's id alone, every
  send answered as having created nothing and nothing of it ever shown: the owner's gate-D ruling, item 2), `legacy`
  (every row from before this migration). Only `gone`, `retained_out` and `never_created` resolve. With it, `closed_at`, `closed_seen_at` and `qualified_at` (task 15).
- `tenant_erasures`: `verified_close` (every execution found was verified gone by then: never a bound),
  `absence_unresolved` (for display only), `qualification` (`legacy_completion_unproven`) and `legacy_completed_at`.
- **The rows already there:** every execution row becomes `legacy`. An erasure not yet complete with one keeps its
  close as `verified_close` and loses its bound, so it holds. A completed one keeps its completion, its audit and its
  tenant `erased`, is qualified `legacy_completion_unproven` with `legacy_completed_at`, and is alerted once.
- `dewpoint_retention` updates the four new known-row columns alone.

One transaction, Alembic's own, each lock wait bounded (5 s). Its downgrade refuses while anything it introduced is
kept (a provenance other than `legacy`, a verified close, a qualification), its locks taken before it checks."""

import sqlalchemy as sa
import structlog
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None

log = structlog.get_logger("dewpoint.erasure")
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
PROVENANCE = "'gone', 'run_not_found', 'absent', 'retained_out', 'never_created', 'legacy'"
COLUMNS = [
    "ALTER TABLE tenant_erasure_known ADD COLUMN provenance text NULL, ADD COLUMN closed_at timestamptz NULL, "
    "ADD COLUMN closed_seen_at timestamptz NULL, ADD COLUMN qualified_at timestamptz NULL",
    "ALTER TABLE tenant_erasures ADD COLUMN verified_close timestamptz NULL, "
    "ADD COLUMN absence_unresolved integer NOT NULL DEFAULT 0, "
    "ADD COLUMN qualification text NULL CONSTRAINT tenant_erasures_qualification "
    "CHECK (qualification IN ('legacy_completion_unproven')), ADD COLUMN legacy_completed_at timestamptz NULL",
]
LEGACY = [
    "UPDATE tenant_erasure_known SET provenance = 'legacy' WHERE kind = 'execution'",
    f"ALTER TABLE tenant_erasure_known ADD CONSTRAINT tenant_erasure_known_provenance CHECK (provenance IN ({PROVENANCE})), "
    "ADD CONSTRAINT tenant_erasure_known_provenance_kind CHECK ((kind = 'execution') = (provenance IS NOT NULL))",
    # Not yet complete: its close kept, its bound gone (it holds: a legacy row is unresolved)
    "UPDATE tenant_erasures e SET verified_close = e.latest_close, latest_close = NULL, check_after = NULL "
    "WHERE e.completed_at IS NULL AND EXISTS (SELECT 1 FROM tenant_erasure_known k "
    "WHERE k.tenant_id = e.tenant_id AND k.provenance = 'legacy')",
    "GRANT UPDATE (provenance, closed_at, closed_seen_at, qualified_at) ON tenant_erasure_known TO dewpoint_retention",
]
# Completed: its completion kept, never presented as proven under the current standard
QUALIFIED = """UPDATE tenant_erasures e SET qualification = 'legacy_completion_unproven', legacy_completed_at = e.completed_at
WHERE e.completed_at IS NOT NULL AND EXISTS (SELECT 1 FROM tenant_erasure_known k
                                            WHERE k.tenant_id = e.tenant_id AND k.provenance = 'legacy')
RETURNING e.tenant_id, (SELECT count(*) FROM tenant_erasure_known k
                        WHERE k.tenant_id = e.tenant_id AND k.provenance = 'legacy')"""

LOCKED = "LOCK TABLE tenant_erasures, tenant_erasure_known IN ACCESS EXCLUSIVE MODE"
REFUSE_DOWNGRADE = """DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM tenant_erasure_known WHERE provenance <> 'legacy')
     OR EXISTS (SELECT 1 FROM tenant_erasures
                 WHERE verified_close IS NOT NULL OR qualification IS NOT NULL OR legacy_completed_at IS NOT NULL) THEN
    RAISE EXCEPTION '0060 refused: a provenance, a verified close or a qualification is kept (never dropped)';
  END IF;
END $$"""


def upgrade() -> None:
    for statement in (LOCK_TIMEOUT, *COLUMNS, *LEGACY):
        op.execute(statement)
    for tenant_id, legacy in op.get_bind().execute(sa.text(QUALIFIED)).all():
        log.error("erasure_legacy_unproven", tenant=str(tenant_id), legacy=int(legacy))


def downgrade() -> None:
    for statement in (LOCK_TIMEOUT, LOCKED, REFUSE_DOWNGRADE):
        op.execute(statement)
    op.execute("ALTER TABLE tenant_erasure_known DROP CONSTRAINT tenant_erasure_known_provenance_kind, "
               "DROP CONSTRAINT tenant_erasure_known_provenance, DROP COLUMN qualified_at, DROP COLUMN closed_seen_at, "
               "DROP COLUMN closed_at, DROP COLUMN provenance")  # fmt: skip
    op.execute("ALTER TABLE tenant_erasures DROP COLUMN legacy_completed_at, DROP COLUMN qualification, "
               "DROP COLUMN absence_unresolved, DROP COLUMN verified_close")  # fmt: skip
