# SPDX-License-Identifier: Apache-2.0
"""Each known execution's provenance (2b-4b M4 recovery, task 11; design revision 5 §5, revision 6 §4 and §7): how the
erasure knows it's gone, written explicitly, never NULL for an execution, never read as anything it doesn't say.

- `gone`: shown, deleted, then read back as not found (its item went `requested` before it was verified);
- `run_not_found`: an exact run whose describe answered NOT_FOUND before the erasure ever showed it;
- `absent`: an id alone, never shown;
- `legacy`: every row from before migration 0060.

Only `gone` (and phase D's `retained_out`) resolves. A conflicting insert never changes a row's provenance; a held one
becomes `gone` only when that exact id is shown, deleted and read back."""

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from dewpoint.apps.erasure import stages
from dewpoint.core.models.erasure import TenantErasureItem
from tests.apps.erasure.fake_temporal import FakeTemporal
from tests.core.retention.support import tenant


async def _erasing(owner: Any) -> uuid.UUID:
    """A tenant whose erasure is at step 60."""
    ctx = await tenant(owner)
    async with owner() as s, s.begin():
        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": ctx["t"]})
        await s.execute(text("insert into tenant_erasures (tenant_id, requested_by, step, fenced_at) "
                             "values (:t, gen_random_uuid(), 60, now())"), {"t": ctx["t"]})  # fmt: skip
    return uuid.UUID(str(ctx["t"]))


def _ctx(retention: Any, tenant_id: uuid.UUID) -> stages.Context:
    return stages.Context(retention, None, tenant_id)  # type: ignore[arg-type]  # the fake Temporal needs no client


async def _item(owner: Any, retention: Any, tenant_id: uuid.UUID, workflow_id: str, run_id: str | None,
                state: str) -> TenantErasureItem:  # fmt: skip
    async with owner() as s, s.begin():
        made = (await s.execute(text("insert into tenant_erasure_items (tenant_id, step, kind, workflow_id, run_id, "
                                     "source, state) values (:t, 60, 'execution', :w, :r, 'tests', :s) returning id"),
                                {"t": tenant_id, "w": workflow_id, "r": run_id, "s": state})).scalar_one()  # fmt: skip
    async with retention() as s:
        await s.execute(text("select set_config('app.tenant_id', :t, false)"), {"t": str(tenant_id)})
        return (await s.execute(select(TenantErasureItem).where(TenantErasureItem.id == made))).scalar_one()


async def _known(owner: Any, tenant_id: uuid.UUID) -> dict[tuple[str, str, str | None], str | None]:
    async with owner() as s:
        found = await s.execute(text("select kind, workflow_id, run_id, provenance from tenant_erasure_known "
                                     "where tenant_id = :t"), {"t": tenant_id})  # fmt: skip
        return {(k, w, r): p for k, w, r, p in found}


async def _record(owner: Any, tenant_id: uuid.UUID, kind: str, workflow_id: str, run_id: str | None,
                  provenance: str | None) -> None:  # fmt: skip
    async with owner() as s, s.begin():
        await s.execute(text("insert into tenant_erasure_known (tenant_id, kind, workflow_id, run_id, provenance) "
                             "values (:t, :k, :w, :r, :p)"),
                        {"t": tenant_id, "k": kind, "w": workflow_id, "r": run_id, "p": provenance})  # fmt: skip


async def test_each_write_path_gives_its_provenance(owner_sessionmaker, retention_sessionmaker) -> None:
    t = await _erasing(owner_sessionmaker)
    ctx = _ctx(retention_sessionmaker, t)
    for workflow_id, run_id, state in (("w:deleted", "r1", "requested"), ("w:never-shown", "r2", "found"),
                                       ("w:id-only", None, "found")):  # fmt: skip
        item = await _item(owner_sessionmaker, retention_sessionmaker, t, workflow_id, run_id, state)
        await stages._mark(ctx, item, "verified", known="execution")
    schedule = await _item(owner_sessionmaker, retention_sessionmaker, t, "s:1", None, "requested")
    await stages._mark(ctx, schedule, "verified", known="schedule")
    assert await _known(owner_sessionmaker, t) == {
        ("execution", "w:deleted", "r1"): "gone", ("execution", "w:never-shown", "r2"): "run_not_found",
        ("execution", "w:id-only", None): "absent", ("schedule", "s:1", None): None,
    }  # fmt: skip


async def test_an_id_shown_then_deleted_is_gone_and_one_never_shown_is_held(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    """Through step 60 itself: an id alone whose chain was shown is `requested` (its run handed on), so its later
    NOT_FOUND is `gone`; an id, or an exact run, Temporal never showed is `absent`, or `run_not_found`."""
    t = await _erasing(owner_sessionmaker)
    fake = FakeTemporal().install(monkeypatch)
    fake.add("w:shown", "r1")
    async with owner_sessionmaker() as s, s.begin():
        for w, r in (("w:shown", None), ("w:never", None), ("w:gone-run", "r9")):
            await s.execute(text("insert into tenant_erasure_items (tenant_id, step, kind, workflow_id, run_id, "
                                 "source) values (:t, 60, 'execution', :w, :r, 'tests')"),
                            {"t": t, "w": w, "r": r})  # fmt: skip
    ctx = _ctx(retention_sessionmaker, t)
    for _ in range(3):
        await stages.executions(ctx)
    assert await _known(owner_sessionmaker, t) == {
        ("execution", "w:shown", "r1"): "gone", ("execution", "w:shown", None): "gone",
        ("execution", "w:never", None): "absent", ("execution", "w:gone-run", "r9"): "run_not_found",
    }  # fmt: skip


async def test_no_execution_row_is_without_provenance_and_no_schedule_row_has_one(owner_sessionmaker) -> None:
    t = await _erasing(owner_sessionmaker)
    for kind, provenance in (("execution", None), ("schedule", "gone")):
        with pytest.raises(IntegrityError, match="provenance"):
            await _record(owner_sessionmaker, t, kind, "w:1", None, provenance)
    with pytest.raises(IntegrityError, match="provenance"):
        await _record(owner_sessionmaker, t, "execution", "w:2", None, "verified")  # not one of its values


@pytest.mark.parametrize("held", ["legacy", "run_not_found", "absent"])
async def test_a_conflicting_insert_never_changes_a_rows_provenance(
    owner_sessionmaker, retention_sessionmaker, held: str
) -> None:
    t = await _erasing(owner_sessionmaker)
    await _record(owner_sessionmaker, t, "execution", "w:1", "r1", held)
    item = await _item(owner_sessionmaker, retention_sessionmaker, t, "w:1", "r1", "found")
    await stages._mark(_ctx(retention_sessionmaker, t), item, "verified", known="execution")  # its own insert
    assert await _known(owner_sessionmaker, t) == {("execution", "w:1", "r1"): held}


async def test_a_held_row_becomes_gone_only_when_that_exact_id_is_deleted_and_read_back(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    t = await _erasing(owner_sessionmaker)
    for run_id in ("r1", "r2", None):
        await _record(owner_sessionmaker, t, "execution", "w:1", run_id, "legacy")
    item = await _item(owner_sessionmaker, retention_sessionmaker, t, "w:1", "r1", "requested")
    await stages._mark(_ctx(retention_sessionmaker, t), item, "verified", known="execution")
    assert await _known(owner_sessionmaker, t) == {("execution", "w:1", "r1"): "gone",
                                                   ("execution", "w:1", "r2"): "legacy",
                                                   ("execution", "w:1", None): "legacy"}  # fmt: skip
