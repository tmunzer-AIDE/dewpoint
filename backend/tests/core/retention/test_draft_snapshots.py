# SPDX-License-Identifier: Apache-2.0
"""Retention's sweep of draft snapshots (B8; the simulation design §6.2, §6.7): a snapshot no request or run names
goes, after the trees that named it; one an admission is reusing never does, in either order: the admission holding
its lock keeps the sweep off, and one the sweep took before the lock was held is made again."""

import asyncio
import dataclasses
import uuid
from typing import Any

from sqlalchemy import text

from dewpoint.core.db import tenant_scope
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.retention import sweep
from dewpoint.core.workflows import drafts, service
from tests.core.retention.support import OLD, RECENT, count, request, snapshot, tenant, tree

SNAPSHOTS = "select count(*) from draft_snapshots where tenant_id = :t"


async def new_version(owner: Any, ctx: dict[str, Any], version_hash: str) -> service.NewVersion:
    """The tenant's version, as a draft frozen under `version_hash` would carry it."""
    async with owner() as s:
        v = await s.get(WorkflowVersion, ctx["v"])
        assert v is not None
        names = {f.name for f in dataclasses.fields(service.NewVersion)} - {"id", "version_hash", "declassified"}
        return service.NewVersion(id=uuid.uuid4(), version_hash=version_hash, **{n: getattr(v, n) for n in names})


async def admitted(api: Any, ctx: dict[str, Any], new: service.NewVersion, hold: asyncio.Event | None = None,
                   released: asyncio.Event | None = None) -> uuid.UUID:  # fmt: skip
    """An admission's reuse of the snapshot of `new`: held (`hold` set) until `released`, then committed."""
    async with api() as s, s.begin():
        await tenant_scope(s, ctx["t"])
        wf = await service.get_workflow(s, ctx["t"], ctx["w"])
        assert wf is not None
        found = await drafts.snapshot_for(s, wf, new, revision=1, created_by=None)
        if hold is not None and released is not None:
            hold.set()
            await released.wait()
        return found.id


async def test_the_sweep_takes_a_snapshot_nothing_names_and_keeps_the_ones_named(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    ctx = await tenant(owner_sessionmaker)  # a retention of a day
    await snapshot(owner_sessionmaker, ctx)  # nothing names it
    queued = await snapshot(owner_sessionmaker, ctx)
    await request(owner_sessionmaker, ctx, "queued", None, snapshot=queued)
    recent = await snapshot(owner_sessionmaker, ctx)
    await tree(owner_sessionmaker, ctx, RECENT, snapshot=recent)
    old = await snapshot(owner_sessionmaker, ctx)
    await tree(owner_sessionmaker, ctx, OLD, snapshot=old)  # its tree goes first, in the same sweep
    await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])
    async with owner_sessionmaker() as s:
        left = set((await s.execute(text("select id from draft_snapshots where tenant_id = :t"), {"t": ctx["t"]}))
                   .scalars())  # fmt: skip
    assert left == {queued, recent}


async def test_a_snapshot_an_admission_holds_is_never_swept(
    owner_sessionmaker, api_sessionmaker, retention_sessionmaker
) -> None:
    ctx = await tenant(owner_sessionmaker)
    kept = await snapshot(owner_sessionmaker, ctx, version_hash="a" * 64)
    hold, released = asyncio.Event(), asyncio.Event()
    admission = asyncio.create_task(
        admitted(api_sessionmaker, ctx, await new_version(owner_sessionmaker, ctx, "a" * 64), hold, released)
    )
    await hold.wait()
    await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])  # its try-lock finds the admission's: it skips it
    assert await count(owner_sessionmaker, SNAPSHOTS, t=ctx["t"]) == 1
    released.set()
    assert await admission == kept
    await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])  # nothing holds or names it now
    assert await count(owner_sessionmaker, SNAPSHOTS, t=ctx["t"]) == 0


async def test_a_snapshot_the_sweep_takes_before_an_admission_holds_it_is_made_again(
    owner_sessionmaker, api_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    ctx = await tenant(owner_sessionmaker)
    taken = await snapshot(owner_sessionmaker, ctx, version_hash="b" * 64)
    found, go = asyncio.Event(), asyncio.Event()

    async def paused() -> None:  # the admission found the snapshot and holds nothing yet
        found.set()
        await go.wait()

    monkeypatch.setattr(drafts, "_found", paused)
    admission = asyncio.create_task(
        admitted(api_sessionmaker, ctx, await new_version(owner_sessionmaker, ctx, "b" * 64))
    )
    await found.wait()
    await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])
    assert await count(owner_sessionmaker, SNAPSHOTS, t=ctx["t"]) == 0
    go.set()
    again = await admission
    assert again != taken and await count(owner_sessionmaker, SNAPSHOTS, t=ctx["t"]) == 1
