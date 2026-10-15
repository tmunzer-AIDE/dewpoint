# SPDX-License-Identifier: Apache-2.0
"""Draft snapshots (B8; the simulation design §6.1, §6.2): a workflow's draft frozen for a simulation, one per
workflow and `version_hash`, and how admission's reuse of one holds off retention's sweep of it.

Both take a transaction-scoped advisory lock keyed on the deduplication identity (tenant, workflow, `version_hash`),
never the snapshot's id, so a snapshot made again after the sweep took it is held by the same lock. No row locks, so
no UPDATE grant (as the admission lock reasons, `service.lock_for_admission`): admission inserts the snapshot if it's
new, takes the lock shared, reads the row again in a fresh statement (READ COMMITTED), inserts it again if the sweep
took it meanwhile, and its request names it before the lock is released, at commit. The sweep try-locks each candidate
exclusively, skips it if busy, and deletes it only if, in a fresh statement, nothing names it."""

import dataclasses
import uuid

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.models.workflows import DraftSnapshot, Workflow
from dewpoint.core.workflows.service import NewVersion

_HELD = text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:k, 0))")
_TRY = text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))")
_UNNAMED = (
    "NOT EXISTS (SELECT 1 FROM run_requests q WHERE q.draft_snapshot_id = s.id) "
    "AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.draft_snapshot_id = s.id)"
)
_CANDIDATES = text(
    f"SELECT s.id, s.workflow_id, s.version_hash FROM draft_snapshots s WHERE {_UNNAMED} "  # noqa: S608
    "ORDER BY s.created_at, s.id LIMIT :n"
)
_DELETE = text(f"DELETE FROM draft_snapshots s WHERE s.id = :id AND {_UNNAMED}")  # noqa: S608


async def _found() -> None:
    """Hook between finding or inserting the snapshot and holding its lock. A no-op; the race tests pause here."""


def lock_key(tenant_id: uuid.UUID, workflow_id: uuid.UUID, version_hash: str) -> str:
    return f"dewpoint:draft:{tenant_id}:{workflow_id}:{version_hash}"


async def snapshot_for(
    s: AsyncSession, wf: Workflow, new: NewVersion, *, revision: int, created_by: uuid.UUID | None
) -> DraftSnapshot:
    """`new`'s snapshot of `wf`'s draft, found or inserted, then held against the sweep until this transaction ends. A
    reused one keeps the revision and author of its first freezing."""
    fields = {f.name: getattr(new, f.name) for f in dataclasses.fields(new) if f.name != "id"}
    add = (
        insert(DraftSnapshot)
        .values(tenant_id=wf.tenant_id, workflow_id=wf.id, draft_revision=revision, created_by=created_by, **fields)
        .on_conflict_do_nothing(constraint="draft_snapshots_hash")
    )
    await s.execute(add)
    await _found()
    await s.execute(_HELD, {"k": lock_key(wf.tenant_id, wf.id, new.version_hash)})
    for _ in range(2):  # a fresh statement: the sweep may have taken it before the lock was held
        found = await s.execute(
            select(DraftSnapshot)
            .where(DraftSnapshot.workflow_id == wf.id, DraftSnapshot.version_hash == new.version_hash)
            .execution_options(populate_existing=True)
        )
        snapshot = found.scalar_one_or_none()
        if snapshot is not None:
            return snapshot
        await s.execute(add)
    raise RuntimeError("a draft snapshot inserted under its lock wasn't found")


async def sweep(s: AsyncSession, tenant_id: uuid.UUID, n: int) -> tuple[int, int]:
    """Up to `n` of the tenant's snapshots no request or run names, each deleted unless an admission holds it: (chosen,
    deleted). The caller holds the tenant's scope."""
    chosen = (await s.execute(_CANDIDATES, {"n": n})).all()
    deleted = 0
    for snapshot_id, workflow_id, version_hash in chosen:
        if (await s.execute(_TRY, {"k": lock_key(tenant_id, workflow_id, version_hash)})).scalar():
            deleted += (await s.execute(_DELETE, {"id": snapshot_id})).rowcount  # type: ignore[attr-defined]
    return len(chosen), deleted
