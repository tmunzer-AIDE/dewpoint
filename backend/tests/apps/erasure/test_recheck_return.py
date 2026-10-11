# SPDX-License-Identifier: Apache-2.0
"""The lifelong check covers incomplete erasures; the last resolution returns an erasure through step 60 (2b-4b M4
recovery, task 14; design revision 5 §6, revision 7 §3).

- `erasures_rechecked()` (0062): every completed erasure, and every one past step 60 with anything unresolved (held at
  90, at 70 or 80, stopped or not), read from the rows, never from the display counter. Each is described again on the
  retention sweep's interval: a sighting reopens it (a stopped one is alerted, and waits for its retry).
- A resolution takes the erasure row's lock first, applies, then re-reads what's unresolved: with nothing left, an
  erasure past 60 and not completed goes back to step 60 (a compare-and-set, its bound NULL, audited
  `tenant.erasure.resolved`). Step 60's next advance sets the bound: never earlier than the resolution.
- A late definitive answer (a send's own call, recorded by the dispatcher) is applied by the recheck: `deleted_open`
  becomes `gone` once nothing is open and no answer names another run, or `identified` again with the run one names; a
  `pending` or `unresolved` blocker every answer of which certainly created nothing is removed, its record audited.
- The backstop at 90: nothing unresolved and no bound returns the erasure, alerted `bound_unset`; it never sets one."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import structlog
from sqlalchemy import text

from dewpoint.apps.erasure import bound, process
from dewpoint.core.models.erasure import Stage
from tests.apps.erasure.fake_temporal import FakeTemporal
from tests.apps.erasure.test_blocker_identity import _audited, _blocker, _row
from tests.apps.erasure.test_erasure_bound import _erasure
from tests.apps.erasure.test_provenance import _ctx, _erasing, _known, _record
from tests.core.retention.support import sql

pytestmark = pytest.mark.usefixtures("development_deployment")


async def _at(owner: Any, tenant_id: uuid.UUID, step: int, **values: Any) -> None:
    """The erasure at `step`, with `values` set."""
    sets = "".join(f", {name} = :{name}" for name in values)
    await sql(owner, f"update tenant_erasures set step = :step{sets} where tenant_id = :t",  # noqa: S608  # fixed names
              step=step, t=tenant_id, **values)  # fmt: skip


async def _held(owner: Any, tenant_id: uuid.UUID, *workflow_ids: str) -> None:
    """Held at 90 for `workflow_ids`, each a known id never shown."""
    for workflow_id in workflow_ids:
        await _record(owner, tenant_id, "execution", workflow_id, None, "absent")
    await _at(owner, tenant_id, 90, failure="absence_unresolved", absence_unresolved=len(workflow_ids))


async def _rechecked(retention: Any) -> set[uuid.UUID]:
    async with retention() as s:
        return set((await s.execute(text("select erasures_rechecked()"))).scalars())


async def _audits(owner: Any, tenant_id: uuid.UUID, action: str) -> int:
    async with owner() as s:
        found = await s.execute(text("select count(*) from audit_log where tenant_id = :t and action = :a"),
                                {"t": tenant_id, "a": action})  # fmt: skip
        return int(found.scalar_one())


def _gone(tenant_id: uuid.UUID, workflow_id: str) -> Any:
    """A resolution: the known id `workflow_id` resolved (as a `retained_out` qualification would, task 15)."""

    async def apply(s: Any) -> bool:
        await s.execute(text("update tenant_erasure_known set provenance = 'gone' where tenant_id = :t "
                             "and workflow_id = :w"), {"t": tenant_id, "w": workflow_id})  # fmt: skip
        return True

    return apply


async def test_the_recheck_selects_completed_erasures_and_each_past_60_with_anything_unresolved(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    now = datetime.now(UTC)
    held, at_70, stopped, done, clean, at_60, early = [await _erasing(owner_sessionmaker) for _ in range(7)]
    for t in (held, at_70, stopped, at_60):
        await _record(owner_sessionmaker, t, "execution", "w:1", None, "absent")
    await _at(owner_sessionmaker, held, 90, failure="absence_unresolved", absence_unresolved=1)
    await _at(owner_sessionmaker, at_70, 70)
    await _at(owner_sessionmaker, stopped, 80, stopped_at=now)
    await _at(owner_sessionmaker, done, 100, completed_at=now)
    await _at(owner_sessionmaker, clean, 90)  # nothing unresolved: the bound, then the final check
    await _blocker(owner_sessionmaker, early)
    await _at(owner_sessionmaker, early, 40)  # before the fence: its stages are still running
    selected = await _rechecked(retention_sessionmaker)
    assert {held, at_70, stopped, done} <= selected
    assert not {clean, at_60, early} & selected


async def test_a_counter_forced_to_zero_is_still_selected_while_its_rows_are_unresolved(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    t = await _erasing(owner_sessionmaker)
    await _held(owner_sessionmaker, t, "w:1")
    await _at(owner_sessionmaker, t, 90, absence_unresolved=0)
    assert t in await _rechecked(retention_sessionmaker)


async def test_a_sighting_reopens_an_incomplete_erasure_and_a_stopped_one_is_alerted_and_waits(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    held, stopped = await _erasing(owner_sessionmaker), await _erasing(owner_sessionmaker)
    fake = FakeTemporal().install(monkeypatch)
    for t in (held, stopped):
        await _held(owner_sessionmaker, t, f"w:{t}")
        fake.add(f"w:{t}", "r1")  # shown now
    await _at(owner_sessionmaker, stopped, 80, stopped_at=datetime.now(UTC))
    with structlog.testing.capture_logs() as logs:
        await bound.reconcile_erased(retention_sessionmaker, None)  # type: ignore[arg-type]
    assert [(await _erasure(owner_sessionmaker, t)).step for t in (held, stopped)] == [60, 60]
    alerted = {e["tenant"] for e in logs if e["event"] == "erasure_incident" and e["log_level"] == "error"}
    assert {str(held), str(stopped)} <= alerted
    assert await process.advance(retention_sessionmaker, None, stopped) == Stage.EXECUTIONS  # type: ignore[arg-type]
    assert ("delete", f"w:{stopped}", "r1") not in fake.calls  # it waits for its retry
    assert (await _erasure(owner_sessionmaker, stopped)).stopped_at is not None


async def test_the_last_item_resolved_at_90_returns_the_erasure_and_its_next_bound_starts_after_the_resolution(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    """The owner's case."""
    t = await _erasing(owner_sessionmaker)
    FakeTemporal().install(monkeypatch)
    await _held(owner_sessionmaker, t, "w:1")
    assert await bound.resolve(retention_sessionmaker, t, _gone(t, "w:1")) is True
    returned = await _erasure(owner_sessionmaker, t)
    assert (returned.step, returned.latest_close, returned.check_after, returned.failure) == (60, None, None, None)
    assert await _audits(owner_sessionmaker, t, "tenant.erasure.resolved") == 1
    assert await process.advance(retention_sessionmaker, None, t) == Stage.BOUND  # type: ignore[arg-type]
    after = await _erasure(owner_sessionmaker, t)
    assert after.latest_close > returned.step_at  # set by step 60's advance, after the resolution
    assert after.check_after == after.latest_close + bound.NAMESPACE_RETENTION_MAX


async def test_a_late_answer_turning_deleted_open_into_gone_returns_it_the_same_way(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    FakeTemporal().install(monkeypatch)
    w, request_id, rid = await _blocker(owner_sessionmaker, t, state="deleted_open", identified="r1", open_send=True)
    await _held(owner_sessionmaker, t, w)  # its known id `absent`, as step 60 left it
    await bound.reconcile_erased(retention_sessionmaker, None)  # type: ignore[arg-type]
    assert (await _erasure(owner_sessionmaker, t)).step == 90  # its send still open: nothing to apply
    await sql(owner_sessionmaker, "update start_sends set answer = 'refused', answered_at = now() "
              "where request_id = :r", r=request_id)  # fmt: skip  # the late call's own answer
    await bound.reconcile_erased(retention_sessionmaker, None)  # type: ignore[arg-type]
    assert await _row(owner_sessionmaker, request_id) is None
    assert await _audited(owner_sessionmaker, request_id) == [
        {"run_id": "r1", "start_request_id": str(rid), "late_start": None, "late_start_at": None}
    ]
    assert await _known(owner_sessionmaker, t) == {("execution", w, None): "gone"}
    returned = await _erasure(owner_sessionmaker, t)
    assert (returned.step, returned.latest_close) == (60, None)
    assert await _audits(owner_sessionmaker, t, "tenant.erasure.resolved") == 1


async def test_a_late_answer_naming_another_run_identifies_the_blocker_again(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    FakeTemporal().install(monkeypatch)
    w, request_id, _ = await _blocker(owner_sessionmaker, t, state="deleted_open", identified="r1", open_send=True)
    await _held(owner_sessionmaker, t, w)
    await sql(owner_sessionmaker, "update start_sends set answer = 'started', run_id = 'r2', answered_at = now() "
              "where request_id = :r", r=request_id)  # fmt: skip
    await bound.reconcile_erased(retention_sessionmaker, None)  # type: ignore[arg-type]
    assert (await _row(owner_sessionmaker, request_id) or ())[:2] == ("identified", "r2")  # that run: the erasure's
    assert (await _erasure(owner_sessionmaker, t)).step == 90


async def _certainly_nothing(owner: Any, tenant_id: uuid.UUID, **blocker: Any) -> tuple[str, uuid.UUID, uuid.UUID]:
    """A blocker of the tenant held at 90 as step 60 left it (its id alone `absent`, as known and as an item), whose
    open send then answers `refused`: every answer certainly created nothing."""
    w, request_id, rid = await _blocker(owner, tenant_id, state="unresolved", open_send=True, **blocker)
    await _held(owner, tenant_id, w)
    await sql(owner, "insert into tenant_erasure_items (tenant_id, step, kind, workflow_id, source, state) "
              "values (:t, 60, 'execution', :w, 'blocker', 'absent')", t=tenant_id, w=w)  # fmt: skip
    await sql(owner, "update start_sends set answer = 'refused', answered_at = now() where request_id = :r",
              r=request_id)  # fmt: skip
    return w, request_id, rid


async def _id_alone(owner: Any, tenant_id: uuid.UUID, workflow_id: str) -> tuple[str | None, str | None]:
    """The id alone's (known provenance, item state)."""
    async with owner() as s:
        known = (await s.execute(text("select provenance from tenant_erasure_known where tenant_id = :t "
                                      "and workflow_id = :w and run_id is null"),
                                 {"t": tenant_id, "w": workflow_id})).scalar()  # fmt: skip
        item = (await s.execute(text("select state from tenant_erasure_items where tenant_id = :t and step = 60 "
                                     "and workflow_id = :w and run_id is null"),
                                {"t": tenant_id, "w": workflow_id})).scalar()  # fmt: skip
    return known, item


async def test_the_last_blocker_whose_sends_all_created_nothing_goes_its_id_never_created_and_it_returns_through_60(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    """The owner's gate-D ruling, item 2: the request-unique id never held its erasure for good. Removed, audited; its
    id alone `never_created`, known row and item, in the same locked transaction; the last one, so the erasure returns
    through step 60, whose next advance sets the bound."""
    t = await _erasing(owner_sessionmaker)
    FakeTemporal().install(monkeypatch)
    w, request_id, rid = await _certainly_nothing(owner_sessionmaker, t)
    await bound.reconcile_erased(retention_sessionmaker, None)  # type: ignore[arg-type]
    assert await _row(owner_sessionmaker, request_id) is None
    async with owner_sessionmaker() as s:
        details = list((await s.execute(text("select details from audit_log where action = "
                                             "'run.request.start_removed' and target_id = :r"),
                                        {"r": str(request_id)})).scalars())  # fmt: skip
    assert details == [{"run_id": None, "start_request_id": str(rid), "late_start": None, "late_start_at": None}]
    assert await _id_alone(owner_sessionmaker, t, w) == ("never_created", "verified")
    returned = await _erasure(owner_sessionmaker, t)
    assert (returned.step, returned.latest_close) == (60, None)
    assert await _audits(owner_sessionmaker, t, "tenant.erasure.resolved") == 1
    assert await process.advance(retention_sessionmaker, None, t) == Stage.BOUND  # type: ignore[arg-type]
    after = await _erasure(owner_sessionmaker, t)
    assert after.latest_close > returned.step_at


@pytest.mark.parametrize("shown", ["a late start recorded", "a run of its id known", "its id alone shown",
                                   "seen in the evidence"])  # fmt: skip
async def test_its_id_stays_held_if_any_execution_of_it_was_shown(
    owner_sessionmaker, retention_sessionmaker, monkeypatch, shown: str
) -> None:
    """Nothing created, yet something with that id was shown: contradictory, so the id stays `absent` and the erasure
    held (fail-closed); the blocker itself goes, its record audited."""
    t = await _erasing(owner_sessionmaker)
    FakeTemporal().install(monkeypatch)
    late = {"late_start": "unmatched"} if shown == "a late start recorded" else {}
    w, request_id, _ = await _certainly_nothing(owner_sessionmaker, t, **late)
    if shown == "a run of its id known":
        await sql(owner_sessionmaker, "insert into tenant_erasure_known (tenant_id, kind, workflow_id, run_id, "
                  "provenance) values (:t, 'execution', :w, 'r9', 'gone')", t=t, w=w)  # fmt: skip
    if shown == "its id alone shown":
        await sql(owner_sessionmaker, "update tenant_erasure_items set state = 'verified', verified_at = now() "
                  "where tenant_id = :t and workflow_id = :w", t=t, w=w)  # fmt: skip
    if shown == "seen in the evidence":  # written as before the fence, which the test lifts for it alone
        await sql(owner_sessionmaker, "update tenant_erasures set fenced_at = null where tenant_id = :t", t=t)
        await sql(owner_sessionmaker, "insert into execution_evidence (tenant_id, workflow_id, started_at, seen_at) "
                  "values (:t, :w, now(), now())", t=t, w=w)  # fmt: skip
        await sql(owner_sessionmaker, "update tenant_erasures set fenced_at = now() where tenant_id = :t", t=t)
    await bound.reconcile_erased(retention_sessionmaker, None)  # type: ignore[arg-type]
    assert await _row(owner_sessionmaker, request_id) is None
    assert (await _id_alone(owner_sessionmaker, t, w))[0] == "absent"
    assert (await _erasure(owner_sessionmaker, t)).step == 90


async def test_a_legacy_blocker_is_never_removed_on_late_answers(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    FakeTemporal().install(monkeypatch)
    w, request_id, _ = await _certainly_nothing(owner_sessionmaker, t, legacy=True)
    await bound.reconcile_erased(retention_sessionmaker, None)  # type: ignore[arg-type]
    assert (await _row(owner_sessionmaker, request_id) or ())[0] == "unresolved"  # ruling 1
    assert await _id_alone(owner_sessionmaker, t, w) == ("absent", "absent")


async def test_two_concurrent_resolutions_of_the_last_two_items_return_it_exactly_once(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    t = await _erasing(owner_sessionmaker)
    await _held(owner_sessionmaker, t, "w:1", "w:2")
    applied = {w: asyncio.Event() for w in ("w:1", "w:2")}

    def resolving(workflow_id: str, other: str) -> Any:
        async def apply(s: Any) -> bool:
            await _gone(t, workflow_id)(s)
            applied[workflow_id].set()
            with contextlib.suppress(TimeoutError):  # both applied before either re-reads, unless they serialize
                await asyncio.wait_for(applied[other].wait(), 2)
            return True

        return apply

    returns = await asyncio.gather(bound.resolve(retention_sessionmaker, t, resolving("w:1", "w:2")),
                                   bound.resolve(retention_sessionmaker, t, resolving("w:2", "w:1")))  # fmt: skip
    assert sorted(returns) == [False, True]
    assert await _audits(owner_sessionmaker, t, "tenant.erasure.resolved") == 1
    assert (await _erasure(owner_sessionmaker, t)).step == 60


async def test_a_resolution_racing_step_60s_advance_ends_with_a_bound_or_a_return(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)  # at 60, every item settled
    await _record(owner_sessionmaker, t, "execution", "w:1", None, "absent")
    decided = asyncio.Event()
    original = bound._return_to_executions

    async def held_open(s: Any, tenant_id: uuid.UUID) -> bool:
        returned = await original(s, tenant_id)
        decided.set()
        await asyncio.sleep(1)  # its transaction still open: the advance runs meanwhile
        return returned

    monkeypatch.setattr(bound, "_return_to_executions", held_open)

    async def advanced() -> Stage:
        await decided.wait()
        return await process._moved(retention_sessionmaker, t, Stage.EXECUTIONS)

    returned, _ = await asyncio.gather(bound.resolve(retention_sessionmaker, t, _gone(t, "w:1")), advanced())
    erasure = await _erasure(owner_sessionmaker, t)
    assert erasure.latest_close is not None or (returned and erasure.step == Stage.EXECUTIONS)


async def test_an_advance_from_60_never_leaves_behind_an_item_a_reopen_added_after_the_stage_settled(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    """Another retention process's recheck reopens the erasure between step 60's settling and its advance: the advance,
    under the erasure row's lock, sees the found item and stays (the final review's ruling b)."""
    t = await _erasing(owner_sessionmaker)  # at 60, every item settled
    await sql(owner_sessionmaker, "insert into tenant_erasure_items (tenant_id, step, kind, workflow_id, run_id, "
              "source) values (:t, 60, 'execution', 'w:late', 'r1', 'reconciliation')", t=t)  # fmt: skip
    assert await process._moved(retention_sessionmaker, t, Stage.EXECUTIONS) == Stage.EXECUTIONS
    erasure = await _erasure(owner_sessionmaker, t)
    assert (erasure.step, erasure.latest_close, erasure.verified_close) == (60, None, None)


async def test_the_backstop_returns_an_erasure_at_90_with_nothing_unresolved_and_no_bound_and_never_sets_one(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    FakeTemporal().install(monkeypatch)
    await _at(owner_sessionmaker, t, 90)  # nothing unresolved, and no bound
    with structlog.testing.capture_logs() as logs:
        assert await bound.check(_ctx(retention_sessionmaker, t)) == "returned"
    erasure = await _erasure(owner_sessionmaker, t)
    assert (erasure.step, erasure.latest_close, erasure.check_after) == (60, None, None)
    assert [e["log_level"] for e in logs if e["event"] == "bound_unset"] == ["error"]
    assert await _audits(owner_sessionmaker, t, "tenant.erasure.resolved") == 1
    await _at(owner_sessionmaker, t, 90)  # again, now through the advance: carried on from 60
    assert await process.advance(retention_sessionmaker, None, t) == Stage.BOUND  # type: ignore[arg-type]
    after = await _erasure(owner_sessionmaker, t)  # step 60's advance set the bound
    assert after.latest_close is not None and after.latest_close > erasure.step_at
