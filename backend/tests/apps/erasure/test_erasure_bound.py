# SPDX-License-Identifier: Apache-2.0
"""Step 60 settles without claiming verification; no bound while anything is unresolved (2b-4b M4 recovery, task 12;
design revision 4 §3, revision 5 §3 and §7, revision 6 §7).

- An id alone that every describe answered NOT_FOUND, never shown, is `absent`: never `verified`. Step 60 advances once
  every item is `verified` or `absent` (`_settled`), always recording `verified_close`, and the bound (`latest_close`,
  `check_after`) only if nothing is unresolved for the tenant, read in the advance's own transaction.
- "Unresolved" (`erasure_unresolved`): a known execution `absent`, `run_not_found` or `legacy`; an `absent` item; any of
  the tenant's `unresolved_sends`. Step 90 holds `absence_unresolved` before anything else, alerted when the hold
  starts and when its count changes; nothing completes and no item is deleted while it holds.
- `erasure_proven`: completed, no qualification, nothing unresolved."""

import uuid
from typing import Any

import pytest
import structlog
from sqlalchemy import text

from dewpoint.apps.erasure import bound, process, stages
from dewpoint.core.models.erasure import Stage
from tests.apps.erasure.fake_temporal import FakeTemporal
from tests.apps.erasure.test_provenance import _ctx, _erasing, _known, _record

pytestmark = pytest.mark.usefixtures("development_deployment")


async def _items(owner: Any, tenant_id: uuid.UUID, *pairs: tuple[str, str | None]) -> None:
    async with owner() as s, s.begin():
        for workflow_id, run_id in pairs:
            await s.execute(text("insert into tenant_erasure_items (tenant_id, step, kind, workflow_id, run_id, "
                                 "source) values (:t, 60, 'execution', :w, :r, 'tests')"),
                            {"t": tenant_id, "w": workflow_id, "r": run_id})  # fmt: skip


async def _states(owner: Any, tenant_id: uuid.UUID) -> dict[tuple[str, str | None], str]:
    async with owner() as s:
        found = await s.execute(text("select workflow_id, run_id, state from tenant_erasure_items "
                                     "where tenant_id = :t and step = 60"), {"t": tenant_id})  # fmt: skip
        return {(w, r): state for w, r, state in found}


async def _erasure(owner: Any, tenant_id: uuid.UUID) -> Any:
    async with owner() as s:
        return (await s.execute(text("select * from tenant_erasures where tenant_id = :t"), {"t": tenant_id})).one()


async def _unresolved(retention: Any, tenant_id: uuid.UUID) -> int:
    async with retention() as s:
        return int((await s.execute(text("select erasure_unresolved(:t)"), {"t": tenant_id})).scalar_one())


async def test_an_id_never_shown_is_absent_never_verified(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    FakeTemporal().install(monkeypatch)
    await _items(owner_sessionmaker, t, ("w:never", None))
    for _ in range(2):
        assert await stages.executions(_ctx(retention_sessionmaker, t)) is True  # settled: nothing found or requested
    assert await _states(owner_sessionmaker, t) == {("w:never", None): "absent"}
    assert await _known(owner_sessionmaker, t) == {("execution", "w:never", None): "absent"}


async def test_an_advance_with_an_absent_item_records_its_verified_close_and_no_bound_and_90_holds_first(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    fake = FakeTemporal().install(monkeypatch)
    fake.add("w:shown", "r1")
    await _items(owner_sessionmaker, t, ("w:never", None), ("w:shown", "r1"))
    with structlog.testing.capture_logs() as logs:
        for _ in range(3):  # the run deleted, then read back; then 70, 80 and 90
            at = await process.advance(retention_sessionmaker, None, t)  # type: ignore[arg-type]
    assert at == Stage.BOUND
    erasure = await _erasure(owner_sessionmaker, t)
    assert erasure.verified_close is not None and (erasure.latest_close, erasure.check_after) == (None, None)
    assert (erasure.failure, erasure.absence_unresolved) == ("absence_unresolved", 2)  # its item and its known row
    held = [(e["log_level"], e["reason"]) for e in logs if e["event"] == "erasure_held"]
    assert held == [("error", "absence_unresolved"), ("info", "absence_unresolved")]  # first; its next look at info
    assert ("w:never", None) in await _states(owner_sessionmaker, t)  # its items kept: nothing completes


async def test_the_hold_alerts_when_it_starts_and_when_its_count_changes_its_hourly_look_at_info(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    FakeTemporal().install(monkeypatch)
    await _items(owner_sessionmaker, t, ("w:never", None))
    levels = []
    for extra in (None, None, ("w:another", "r9")):
        if extra is not None:
            await _record(owner_sessionmaker, t, "execution", *extra, "run_not_found")
        with structlog.testing.capture_logs() as logs:
            await process.advance(retention_sessionmaker, None, t)  # type: ignore[arg-type]
        levels.append([e["log_level"] for e in logs if e["event"] == "erasure_held"])
    assert levels == [["error"], ["info"], ["error"]]
    assert (await _erasure(owner_sessionmaker, t)).absence_unresolved == 3


async def test_with_nothing_unresolved_the_bound_is_the_advances_own_time(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    fake = FakeTemporal().install(monkeypatch)
    fake.add("w:shown", "r1")
    await _items(owner_sessionmaker, t, ("w:shown", "r1"))
    for _ in range(2):
        await process.advance(retention_sessionmaker, None, t)  # type: ignore[arg-type]
    erasure = await _erasure(owner_sessionmaker, t)
    assert erasure.step == Stage.BOUND and erasure.failure == "firing_bound_unproven"  # past the absence hold
    assert erasure.latest_close == erasure.verified_close is not None
    assert erasure.check_after == erasure.latest_close + bound.NAMESPACE_RETENTION_MAX


async def test_the_predicate_counts_each_of_its_three_sources(owner_sessionmaker, retention_sessionmaker) -> None:
    t, other = await _erasing(owner_sessionmaker), await _erasing(owner_sessionmaker)
    for provenance, run_id in (("absent", None), ("run_not_found", "r1"), ("legacy", "r2"), ("gone", "r3"),
                               ("retained_out", "r4")):  # fmt: skip
        await _record(owner_sessionmaker, t, "execution", f"w:{provenance}", run_id, provenance)
    await _record(owner_sessionmaker, other, "execution", "w:theirs", None, "absent")
    assert await _unresolved(retention_sessionmaker, t) == 3  # the resolved two aside, another tenant's aside
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into tenant_erasure_items (tenant_id, step, kind, workflow_id, run_id, source, "
                             "state) values (:t, 60, 'execution', 'w:item', null, 'tests', 'absent')"),
                        {"t": t})  # fmt: skip
        await s.execute(text("insert into unresolved_sends (request_id, tenant_id, workflow_id, legacy_unknown, state) "
                             "values (gen_random_uuid(), :t, 'w:blocked', true, 'unresolved')"), {"t": t})  # fmt: skip
    assert await _unresolved(retention_sessionmaker, t) == 5


@pytest.mark.parametrize(("qualified", "unresolved", "proven"), [(False, False, True), (True, False, False),
                                                                   (False, True, False)])  # fmt: skip
async def test_a_completion_is_proven_only_unqualified_with_nothing_unresolved(
    owner_sessionmaker, retention_sessionmaker, qualified: bool, unresolved: bool, proven: bool
) -> None:
    t = await _erasing(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update tenant_erasures set step = 100, completed_at = now(), qualification = case when "
                             ":q then 'legacy_completion_unproven' end where tenant_id = :t"),
                        {"q": qualified, "t": t})  # fmt: skip
    if unresolved:
        await _record(owner_sessionmaker, t, "execution", "w:1", "r1", "legacy")
    async with retention_sessionmaker() as s:
        assert (await s.execute(text("select erasure_proven(:t)"), {"t": t})).scalar_one() is proven
