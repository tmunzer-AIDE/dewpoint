# SPDX-License-Identifier: Apache-2.0
"""Online equivalents of main's 0047, 0045 and 0070, which main wrote to run in one transaction and which now sit on
D15's path (the owner's rulings at the merge, 2026-10-11). Their files stay byte-identical; a database that hasn't
applied one runs its equivalent here instead, in `online.py`'s steps, ending exactly where the original's body does
(`tests/migrations/test_equivalents.py` proves it against those bodies):

- 0047: its index on `runs` built concurrently, so no write to `runs` waits for it;
- 0045: its table made with its keys, row-level security, policy and fence in one step (a new table's keys share what
  they reference), its grants last, then its index on `runs` built concurrently;
- 0070: its column added in a step, its lock waiting at most a step's budget.

The statements are the originals' own, as Alembic renders their bodies, an index's made concurrent. env.py installs
the equivalents (`install`), each in place of its original's `upgrade()`, after checking every original's file is the
one its equivalent stands for: one that changed refuses the upgrade, naming it, before any migration runs
(`EquivalentStaleError`), so neither an edited body nor a stale equivalent runs silently. Offline (SQL script) mode
refuses them (`EquivalentOfflineError`): a script would hold the original bodies. Downgrades are the originals' own."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migrations.online import exists, grants, index, online, step, ungranted


class EquivalentStaleError(RuntimeError):
    """An original's file isn't the one its equivalent stands for: the upgrade refuses, naming the revision."""


class EquivalentOfflineError(RuntimeError):
    """Offline SQL would hold an original's body, which D15's path never runs: refused, naming the revision."""


@dataclass(frozen=True)
class Equivalent:
    file: str  # the original's, in versions/
    sha256: str  # that file's digest when this equivalent was written
    upgrade: Callable[[], None]


# Each index as its original defines it, built concurrently (online.index's required form)
CONCURRENT = {
    "runs_workflow_last": "CREATE INDEX CONCURRENTLY IF NOT EXISTS runs_workflow_last ON runs (workflow_id, mode, "
    "queued_at DESC, id DESC) WHERE kind = 'run'",
    "runs_workflow_ended": "CREATE INDEX CONCURRENTLY IF NOT EXISTS runs_workflow_ended ON runs (workflow_id, "
    "ended_at DESC, id DESC) WHERE ended_at IS NOT NULL",
}

TABLE_0045 = """CREATE TABLE run_step_connections (
    tenant_id UUID NOT NULL,
    run_id UUID NOT NULL,
    step_id UUID NOT NULL,
    iteration_key TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    connection_id UUID NOT NULL,
    type VARCHAR(64) NOT NULL,
    name VARCHAR(100) NOT NULL,
    revision INTEGER NOT NULL,
    context JSONB DEFAULT '{}'::jsonb NOT NULL,
    opened_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (run_id, step_id, iteration_key, attempt, connection_id, revision),
    CONSTRAINT run_step_connections_run FOREIGN KEY(run_id, tenant_id) REFERENCES runs (id, tenant_id) ON DELETE CASCADE,
    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
)"""
ACCESS_0045 = (  # the original's, in its order
    "ALTER TABLE run_step_connections ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE run_step_connections FORCE ROW LEVEL SECURITY",
    "CREATE POLICY run_step_connections_scope ON run_step_connections "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "GRANT SELECT, INSERT ON run_step_connections TO dewpoint_worker",
    "GRANT SELECT ON run_step_connections TO dewpoint_api",
    "CREATE TRIGGER run_step_connections_fence BEFORE INSERT ON run_step_connections FOR EACH ROW "
    "EXECUTE FUNCTION tenant_insert_fence()",
)


def _0047() -> None:
    with online() as conn:
        index(conn, "0047 runs_workflow_last", CONCURRENT["runs_workflow_last"])


def _0045() -> None:
    with online() as conn:
        step(conn, "0045 run_step_connections", TABLE_0045, *ungranted(*ACCESS_0045),
             done=exists("relation", "run_step_connections"))  # fmt: skip
        step(conn, "0045 grants", *grants(*ACCESS_0045))
        index(conn, "0045 runs_workflow_ended", CONCURRENT["runs_workflow_ended"])


def _0070() -> None:
    with online() as conn:
        step(conn, "0070 webhook_endpoints trigger_key", "ALTER TABLE webhook_endpoints ADD COLUMN trigger_key TEXT",
             done=exists("column", "trigger_key", "webhook_endpoints"))  # fmt: skip


ONLINE: dict[str, Equivalent] = {  # main's, in the order they're chained after 0044
    "0047": Equivalent("0047_runs_workflow_last.py",
                       "abf097a7f1158b88f11ba7b028c91d4e4e66afeb2ee372395a8021da7e82ffe3", _0047),
    "0045": Equivalent("0045_run_step_connections.py",
                       "522be6e7aeb719f9fcefae68c8fe027dd3c1d5b15c94185634a396ed136c2b81", _0045),
    "0070": Equivalent("0070_endpoint_trigger.py",
                       "80c50f802f1951d936569a3cf03a1840c4b14a6585365177ea02c198f723643a", _0070),
}  # fmt: skip


def _checked(script: Any) -> list[tuple[Any, Equivalent]]:
    """Every original with its equivalent, each file checked first: one that isn't the file its equivalent stands for
    refuses everything."""
    found = []
    for revision, equivalent in ONLINE.items():
        original = script.get_revision(revision)
        path = Path(original.path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.name != equivalent.file or digest != equivalent.sha256:
            raise EquivalentStaleError(
                f"migration {revision}: {path.name} isn't the file its online equivalent stands for (its sha256 "
                "changed); refused: its equivalent must be written again against it"
            )
        found.append((original, equivalent))
    return found


def install(script: Any) -> None:
    """Each equivalent in place of its original's `upgrade()` (Alembic takes a revision's `module.upgrade` when it
    builds that step), all checked before any is installed."""
    for original, equivalent in _checked(script):
        original.module.upgrade = equivalent.upgrade


def refuse_offline(script: Any) -> None:
    """Offline, each original's `upgrade()` refuses instead of writing its body into the script."""
    for original, _ in _checked(script):

        def refused(revision: str = original.revision) -> None:
            raise EquivalentOfflineError(f"migration {revision} runs online only (D15): offline SQL would hold main's "
                                         "original body; upgrade this range against the database itself")  # fmt: skip

        original.module.upgrade = refused
