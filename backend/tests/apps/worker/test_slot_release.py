# SPDX-License-Identifier: Apache-2.0
"""A root run's slot (engine 2b spec §7.5): its end write releases it in the same transaction, so the tenant's next
request can start as soon as the run's row is terminal. A sub-run holds no slot of its own and never releases its
root's."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service as runs
from dewpoint.engine.runtime.activities import ProjectInput, RunSummary
from tests.core.runs.test_service import seeded_run
from tests.support.keys import FixtureKeys


async def held(owner: Any, tenant: uuid.UUID, run_id: uuid.UUID) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("insert into run_slots (run_id, tenant_id) values (:r, :t)"), {"r": run_id, "t": tenant})


async def slots(owner: Any) -> list[uuid.UUID]:
    async with owner() as s:
        return list((await s.execute(text("select run_id from run_slots"))).scalars())


async def status(owner: Any, tenant: uuid.UUID, run_id: uuid.UUID) -> str | None:
    async with owner() as s, s.begin():
        await tenant_scope(s, tenant)
        run = await runs.get_run(s, run_id)
    return run.status if run else None


def ended(run_id: uuid.UUID, status: str = "succeeded", *, if_running: bool = False) -> RunSummary:
    return RunSummary(str(run_id), status, datetime.now(UTC).isoformat(), if_running=if_running)


async def test_a_root_runs_end_write_releases_its_slot(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    await held(owner_sessionmaker, tenant, run_id)
    await DbRunStore(worker_sessionmaker, FixtureKeys()).project(ProjectInput(str(tenant), [], ended(run_id)))
    assert await status(owner_sessionmaker, tenant, run_id) == "succeeded"
    assert await slots(owner_sessionmaker) == []


async def test_a_sub_runs_end_leaves_its_roots_slot_held(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    """A parent writing the end of a child that ended without one (`if_running`): only the root's own end frees it."""
    tenant, root = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    _, child = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    await held(owner_sessionmaker, tenant, root)
    store = DbRunStore(worker_sessionmaker, FixtureKeys())
    await store.project(ProjectInput(str(tenant), [], ended(child, "cancelled", if_running=True)))
    assert await slots(owner_sessionmaker) == [root]


async def test_an_end_write_the_database_refuses_still_releases_its_slot(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    """The execution ended either way: a refused end write is logged and skipped (2a's rule), and holding its slot
    would only starve the tenant until the reconciler noticed."""
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    await held(owner_sessionmaker, tenant, run_id)
    await DbRunStore(worker_sessionmaker, FixtureKeys()).project(ProjectInput(str(tenant), [], ended(run_id, "bogus")))
    assert await status(owner_sessionmaker, tenant, run_id) == "running"  # refused: the reconciler ends it (§7.6)
    assert await slots(owner_sessionmaker) == []
