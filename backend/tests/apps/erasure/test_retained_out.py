# SPDX-License-Identifier: Apache-2.0
"""`retained_out`, only on qualified historical evidence (2b-4b M4 recovery, task 15; design revision 6 §4, revision 7
§4; ruling 5 on the clock skew).

A known run Temporal never showed the erasure (`run_not_found`) is resolved as `retained_out`, apart from `gone`, only
when it's an exact run whose close Temporal reported (`closed_at`, captured by the evidence cadence from a describe or
the close event, copied by step 60), no blocker names its workflow, and the target's qualification (0063, filled only
by the persistent-target qualification) covers the namespace's life from its registration to the close: a retention
maximum with archival off over all of it, a jitter maximum at the close, and a clock-skew maximum on every interval
covering the close or the NOT_FOUND. A NOT_FOUND observed at a database time at or past the close plus those three
maximums then qualifies it, audited, through a resolution (task 14). Anything missing leaves it `run_not_found`."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select, text

from dewpoint.apps.dispatcher import evidence
from dewpoint.apps.erasure import bound, stages
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.erasure import TenantErasure, TenantErasureKnown
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.erasure.fake_temporal import FakeTemporal
from tests.apps.erasure.test_blocker_identity import _blocker
from tests.apps.erasure.test_erasure_bound import _erasure
from tests.apps.erasure.test_provenance import _ctx, _erasing, _known
from tests.apps.erasure.test_recheck_return import _at, _audits
from tests.core.retention.support import sql, tenant

pytestmark = pytest.mark.usefixtures("development_deployment")

NOW = datetime.now(UTC)
DAY = timedelta(days=1)
LIFE = (NOW - 200 * DAY, NOW + DAY)  # an interval over the namespace's whole life so far
QUALIFIED = {"retention_max": 30 * DAY, "archival_off": True, "jitter_max": timedelta(minutes=30),
             "clock_skew_max": timedelta(minutes=1)}  # fmt: skip


def _namespace() -> str:
    return f"ns-{uuid.uuid4().hex[:12]}"


async def _target(owner: Any, namespace: str, *intervals: dict[str, Any],
                  registered: datetime | None = LIFE[0]) -> None:  # fmt: skip
    """The persistent-target qualification's record for `namespace`: its registration (None: none) and `intervals`,
    each `QUALIFIED` over `LIFE` unless it says otherwise."""
    if registered is not None:
        await sql(owner, "insert into target_namespace_registrations (namespace, registered_at, evidence) "
                  "values (:n, :r, 'tests')", n=namespace, r=registered)  # fmt: skip
    for interval in intervals:
        values = {"valid_from": LIFE[0], "valid_to": LIFE[1], **QUALIFIED, **interval}
        await sql(owner, "insert into target_qualification_intervals (namespace, valid_from, valid_to, retention_max, "
                  "archival_off, jitter_max, clock_skew_max, evidence) values (:n, :valid_from, :valid_to, "
                  ":retention_max, :archival_off, :jitter_max, :clock_skew_max, 'tests')", n=namespace,
                  **values)  # fmt: skip


async def _run_not_found(owner: Any, tenant_id: uuid.UUID, closed_at: datetime | None, *, workflow_id: str = "w:1",
                         provenance: str = "run_not_found") -> None:  # fmt: skip
    await sql(owner, "insert into tenant_erasure_known (tenant_id, kind, workflow_id, run_id, provenance, closed_at, "
              "closed_seen_at) values (:t, 'execution', :w, 'r1', :p, :c, :c)", t=tenant_id, w=workflow_id,
              p=provenance, c=closed_at)  # fmt: skip


async def _qualify(retention: Any, tenant_id: uuid.UUID, namespace: str, *, workflow_id: str = "w:1",
                   observed_at: datetime = NOW) -> bool:  # fmt: skip
    async with retention() as s, s.begin():
        await tenant_scope(s, tenant_id)
        known = (await s.execute(select(TenantErasureKnown).where(TenantErasureKnown.tenant_id == tenant_id,
                                                                  TenantErasureKnown.workflow_id == workflow_id))
                 ).scalar_one()  # fmt: skip
        return await bound._qualify_retained_out(s, known, namespace, observed_at)


async def test_a_closed_run_past_its_qualified_bound_is_retained_out_audited(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    t, ns = await _erasing(owner_sessionmaker), _namespace()
    await _target(owner_sessionmaker, ns, {})
    await _run_not_found(owner_sessionmaker, t, NOW - 60 * DAY)
    assert await _qualify(retention_sessionmaker, t, ns) is True
    assert await _known(owner_sessionmaker, t) == {("execution", "w:1", "r1"): "retained_out"}
    assert await _audits(owner_sessionmaker, t, "tenant.erasure.retained_out") == 1


# each condition missing keeps the row `run_not_found`
MISSING = {
    "no close": (None, [{}]),
    "no interval": (NOW - 60 * DAY, []),
    "an interval starting after the registration": (NOW - 60 * DAY, [{"valid_from": LIFE[0] + DAY}]),
    "a gap in the namespace's life": (NOW - 60 * DAY, [{"valid_to": NOW - 150 * DAY},
                                                        {"valid_from": NOW - 149 * DAY}]),  # fmt: skip
    "archival not off": (NOW - 60 * DAY, [{"archival_off": False}]),
    "no retention maximum": (NOW - 60 * DAY, [{"retention_max": None}]),
    "no jitter": (NOW - 60 * DAY, [{"jitter_max": None}]),
    "the NOT_FOUND before the bound": (NOW - 20 * DAY, [{}]),
    # past the bound without the skew (12 h before now), before it with the skew (12 h after now): review focus 3
    "the skew": (NOW - 30 * DAY - timedelta(minutes=30) - timedelta(hours=12), [{"clock_skew_max": DAY}]),
    "a NULL skew disables it": (NOW - 60 * DAY, [{"clock_skew_max": None}]),
    # the qualification lapsed before the NOT_FOUND: no skew is qualified at that moment (the final review's finding 2)
    "the NOT_FOUND past every interval": (NOW - 60 * DAY, [{"valid_to": NOW - DAY}]),
    "a NULL skew on an interval covering the NOT_FOUND": (
        NOW - 60 * DAY, [{"valid_to": NOW - DAY}, {"valid_from": NOW - DAY, "clock_skew_max": None}]),
}  # fmt: skip


async def test_no_registration_keeps_the_row_run_not_found(owner_sessionmaker, retention_sessionmaker) -> None:
    """Its intervals alone never say where the namespace's life began."""
    t, ns = await _erasing(owner_sessionmaker), _namespace()
    await _target(owner_sessionmaker, ns, {}, registered=None)
    await _run_not_found(owner_sessionmaker, t, NOW - 60 * DAY)
    assert await _qualify(retention_sessionmaker, t, ns) is False
    assert await _known(owner_sessionmaker, t) == {("execution", "w:1", "r1"): "run_not_found"}


async def test_a_close_before_the_registration_is_contradictory_and_never_qualifies(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    """One interval spans both, so coverage alone would pass: a run can't close in a namespace not yet registered (the
    owner's gate-D ruling, item 4)."""
    t, ns = await _erasing(owner_sessionmaker), _namespace()
    await _target(owner_sessionmaker, ns, {}, registered=NOW - 100 * DAY)
    await _run_not_found(owner_sessionmaker, t, NOW - 150 * DAY)
    assert await _qualify(retention_sessionmaker, t, ns) is False
    assert await _known(owner_sessionmaker, t) == {("execution", "w:1", "r1"): "run_not_found"}


@pytest.mark.parametrize("case", list(MISSING))
async def test_each_condition_missing_keeps_the_row_run_not_found(
    owner_sessionmaker, retention_sessionmaker, case: str
) -> None:
    closed_at, intervals = MISSING[case]
    t, ns = await _erasing(owner_sessionmaker), _namespace()
    await _target(owner_sessionmaker, ns, *intervals)
    await _run_not_found(owner_sessionmaker, t, closed_at)
    assert await _qualify(retention_sessionmaker, t, ns) is False
    assert await _known(owner_sessionmaker, t) == {("execution", "w:1", "r1"): "run_not_found"}


async def test_never_for_a_workflow_with_a_blocker_nor_for_a_legacy_row(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    t, ns = await _erasing(owner_sessionmaker), _namespace()
    await _target(owner_sessionmaker, ns, {})
    w, _, _ = await _blocker(owner_sessionmaker, t, state="identified", identified="r1")
    await _run_not_found(owner_sessionmaker, t, NOW - 60 * DAY, workflow_id=w)
    await _run_not_found(owner_sessionmaker, t, NOW - 60 * DAY, workflow_id="w:legacy", provenance="legacy")
    assert await _qualify(retention_sessionmaker, t, ns, workflow_id=w) is False
    assert await _qualify(retention_sessionmaker, t, ns, workflow_id="w:legacy") is False
    assert await _known(owner_sessionmaker, t) == {("execution", w, "r1"): "run_not_found",
                                                   ("execution", "w:legacy", "r1"): "legacy"}  # fmt: skip


async def test_the_recheck_qualifies_the_last_row_at_90_and_returns_the_erasure(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    """The owner's case, with `retained_out` (task 14's resolution)."""
    t, ns = await _erasing(owner_sessionmaker), _namespace()
    fake = FakeTemporal().install(monkeypatch)  # Temporal shows nothing of it
    await _target(owner_sessionmaker, ns, {})
    await _run_not_found(owner_sessionmaker, t, NOW - 60 * DAY)
    await _at(owner_sessionmaker, t, 90, failure="absence_unresolved", absence_unresolved=1)
    await bound.reconcile_erased(retention_sessionmaker, SimpleNamespace(namespace=ns))  # type: ignore[arg-type]
    assert ("describe", "w:1", "r1") in fake.calls  # the NOT_FOUND observed
    assert await _known(owner_sessionmaker, t) == {("execution", "w:1", "r1"): "retained_out"}
    returned = await _erasure(owner_sessionmaker, t)
    assert (returned.step, returned.latest_close) == (60, None)
    assert await _audits(owner_sessionmaker, t, "tenant.erasure.resolved") == 1


async def test_it_is_reported_apart_from_gone_in_the_completion_audit(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    t = await _erasing(owner_sessionmaker)
    await _run_not_found(owner_sessionmaker, t, NOW - 60 * DAY, provenance="retained_out")
    await _run_not_found(owner_sessionmaker, t, None, workflow_id="w:2", provenance="gone")
    ctx = _ctx(retention_sessionmaker, t)
    async with retention_sessionmaker() as s:
        await tenant_scope(s, t)
        record = (await s.execute(select(TenantErasure).where(TenantErasure.tenant_id == t))).scalar_one()
    await bound._complete(ctx, record, "test boundary")
    async with owner_sessionmaker() as s:
        details = (await s.execute(text("select details from audit_log where tenant_id = :t "
                                        "and action = 'tenant.erasure.complete'"), {"t": t})).scalar_one()  # fmt: skip
    assert (details["known"], details["gone"], details["retained_out"]) == (2, 1, 1)


async def test_step_60_copies_the_close_into_the_known_row_it_writes_run_not_found(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    ctx = await tenant(owner_sessionmaker)
    t: uuid.UUID = ctx["t"]
    closed, seen = NOW - 3 * DAY, NOW - 2 * DAY
    await sql(owner_sessionmaker, "insert into execution_evidence (tenant_id, workflow_id, run_id, started_at, "
              "closed_at, closed_seen_at) values (:t, 'w:1', 'r1', :s, :c, :seen)", t=t, s=NOW - 4 * DAY, c=closed,
              seen=seen)  # fmt: skip  # written before the fence
    await sql(owner_sessionmaker, "update tenants set status = 'erasing' where id = :t", t=t)
    await sql(owner_sessionmaker, "insert into tenant_erasures (tenant_id, requested_by, step, fenced_at) "
              "values (:t, gen_random_uuid(), 60, now())", t=t)  # fmt: skip
    FakeTemporal().install(monkeypatch)  # never shown to the erasure
    await stages.executions(_ctx(retention_sessionmaker, t))
    async with owner_sessionmaker() as s:
        row = (await s.execute(text("select provenance, closed_at, closed_seen_at from tenant_erasure_known "
                                    "where tenant_id = :t and run_id = 'r1'"), {"t": t})).one()  # fmt: skip
    assert tuple(row) == ("run_not_found", closed, seen)


async def _due(owner: Any, dispatch: Any, client: Any, tenant_id: uuid.UUID, passes: int = 4) -> None:
    for _ in range(passes):
        await sql(owner, "update execution_evidence set next_check_at = now() where tenant_id = :t", t=tenant_id)
        await evidence.check_evidence(dispatch, client, retention=DAY)


async def test_the_close_is_captured_from_a_describe_of_the_exact_run_and_from_the_close_event(
    server, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx = await tenant(owner_sessionmaker)
    t, client = str(ctx["t"]), server.client
    exact, alone = run_workflow_id(t, str(uuid.uuid4())), run_workflow_id(t, str(uuid.uuid4()))
    closes = {}
    for workflow_id in (exact, alone):
        handle = await client.start_workflow("Unserved", id=workflow_id, task_queue="erasure-unserved")
        await handle.terminate()
        described = await handle.describe()
        closes[workflow_id] = (described.run_id, described.close_time)
    # the exact run's row already read (its history): the describe alone; the id alone: its history's close event
    await sql(owner_sessionmaker, "insert into execution_evidence (tenant_id, workflow_id, run_id, started_at, "
              "read_at, seen_at, checked_at) values (:t, :w, :r, now() - interval '1 hour', now(), now(), now())",
              t=ctx["t"], w=exact, r=closes[exact][0])  # fmt: skip
    await sql(owner_sessionmaker, "insert into execution_evidence (tenant_id, workflow_id, started_at) "
              "values (:t, :w, now() - interval '1 hour')", t=ctx["t"], w=alone)  # fmt: skip
    await _due(owner_sessionmaker, dispatch_sessionmaker, client, ctx["t"], passes=1)  # one visit each: its own source
    async with owner_sessionmaker() as s:
        found = {w: (r, c, seen is not None) for w, r, c, seen in await s.execute(text(
            "select workflow_id, run_id, closed_at, closed_seen_at from execution_evidence where tenant_id = :t"
        ), {"t": ctx["t"]})}  # fmt: skip
    assert found == {exact: (*closes[exact], True), alone: (*closes[alone], True)}
