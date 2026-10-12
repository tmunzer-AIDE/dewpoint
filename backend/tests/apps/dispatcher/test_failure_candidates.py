# SPDX-License-Identifier: Apache-2.0
"""Each pass's pick skips an item its own kind of work holds, or hasn't yet due after a failure (the owner's rulings on
the 2b-4b M3 design, rev 1 and 2; migration 0050): held until an operator releases it, retried once due. Another
kind's failure never hides it: a reconciliation's are counted by its request's phase, so a request that moved on from
the phase its failures were counted in is picked in its next.

The passes clear their successes' counts in one statement, `work_failures_clear`, by tenant and item."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from tests.core.ingress.support import endpoint, record
from tests.core.retention.support import request, run, sql, tenant

STATES = {  # due_at, held_at: a hold hides an item whenever it's due
    "held": ("now() - interval '1 second'", "now()"),
    "waiting": ("now() + interval '1 hour'", "null"),
    "due": ("now() - interval '1 second'", "null"),
}
CASES = [("held", True), ("waiting", True), ("due", False)]


async def failing(owner: Any, tenant_id: uuid.UUID, kind: str, item: uuid.UUID, state: str) -> None:
    due, held = STATES[state]
    await sql(owner, "insert into work_failures (tenant_id, kind, item_id, errors, last_error, due_at, held_at) "
              f"values (:t, :k, :i, 3, 'RuntimeError', {due}, {held})", t=tenant_id, k=kind, i=item)  # fmt: skip


async def picked(dispatch: Any, query: str, **params: Any) -> list[uuid.UUID]:
    async with dispatch() as s:
        return list((await s.execute(text(query), params)).scalars())


@pytest.mark.parametrize(
    ("kind", "state", "hidden"), [*(("dispatch", s, h) for s, h in CASES), ("cancel", "held", False)]
)
async def test_dispatch_picks_a_tenants_next_request_past_one_its_failures_leave(
    owner_sessionmaker, dispatch_sessionmaker, kind: str, state: str, hidden: bool
) -> None:  # fmt: skip
    """A held request never holds back its tenant's queue: the next is picked."""
    ctx = await tenant(owner_sessionmaker)
    first, second = [await request(owner_sessionmaker, ctx, "queued", None) for _ in range(2)]
    await sql(owner_sessionmaker, "update run_requests set queued_at = queued_at + interval '1 day' where id = :i",
              i=second)  # fmt: skip
    await failing(owner_sessionmaker, ctx["t"], kind, first, state)
    found = await picked(dispatch_sessionmaker, "select request_id from dispatch_candidates(10, null, null) "
                         "where tenant_id = :t", t=ctx["t"])  # fmt: skip
    assert found == [second if hidden else first]


async def requested_cancel(owner: Any, ctx: dict[str, Any]) -> uuid.UUID:
    rid = await request(owner, ctx, "started", None)
    await run(owner, ctx, None, run_id=rid)
    await sql(owner, "update run_requests set cancel_requested_at = now() where id = :i", i=rid)
    return rid


@pytest.mark.parametrize(
    ("kind", "state", "hidden"), [*(("cancel", s, h) for s, h in CASES), ("dispatch", "held", False)]
)
async def test_the_cancel_pass_skips_a_cancel_its_failures_leave(
    owner_sessionmaker, dispatch_sessionmaker, kind: str, state: str, hidden: bool
) -> None:  # fmt: skip
    ctx = await tenant(owner_sessionmaker)
    rid = await requested_cancel(owner_sessionmaker, ctx)
    await failing(owner_sessionmaker, ctx["t"], kind, rid, state)
    found = await picked(dispatch_sessionmaker, "select request_id from cancel_candidates(100) where tenant_id = :t",
                         t=ctx["t"])  # fmt: skip
    assert found == ([] if hidden else [rid])


async def in_phase(owner: Any, ctx: dict[str, Any], phase: str) -> uuid.UUID:
    """A request the reconciler picks in `phase`."""
    if phase == "starting":
        return await request(owner, ctx, "starting", None)
    rid = await request(owner, ctx, "started", None)
    await run(owner, ctx, None if phase == "open" else timedelta(minutes=5), run_id=rid)
    if phase == "slot":
        await sql(owner, "insert into run_slots (run_id, tenant_id) values (:i, :t)", i=rid, t=ctx["t"])
    return rid


RECONCILE = "select request_id from reconcile_candidates('0 seconds', '1 minute', 100) where tenant_id = :t"


@pytest.mark.parametrize("phase", ["starting", "open", "slot"])
@pytest.mark.parametrize(("state", "hidden"), CASES)
async def test_the_reconciler_skips_a_request_its_failures_in_this_phase_leave(
    owner_sessionmaker, dispatch_sessionmaker, phase: str, state: str, hidden: bool
) -> None:  # fmt: skip
    ctx = await tenant(owner_sessionmaker)
    rid = await in_phase(owner_sessionmaker, ctx, phase)
    await failing(owner_sessionmaker, ctx["t"], f"reconcile_{phase}", rid, state)
    assert await picked(dispatch_sessionmaker, RECONCILE, t=ctx["t"]) == ([] if hidden else [rid])


@pytest.mark.parametrize(("phase", "earlier"), [("open", "starting"), ("slot", "open"), ("slot", "starting")])
async def test_a_hold_from_an_earlier_phase_never_hides_the_next(
    owner_sessionmaker, dispatch_sessionmaker, phase: str, earlier: str
) -> None:  # fmt: skip
    """The owner's ruling (rev 2): a reconcile failure is distinguished when its request changes phase."""
    ctx = await tenant(owner_sessionmaker)
    rid = await in_phase(owner_sessionmaker, ctx, phase)
    await failing(owner_sessionmaker, ctx["t"], f"reconcile_{earlier}", rid, "held")
    assert await picked(dispatch_sessionmaker, RECONCILE, t=ctx["t"]) == [rid]


@pytest.mark.parametrize(
    ("kind", "state", "hidden"), [*(("subrun", s, h) for s, h in CASES), ("reconcile_open", "held", False)]
)
async def test_the_subrun_pass_skips_an_orphan_its_failures_leave(
    owner_sessionmaker, dispatch_sessionmaker, kind: str, state: str, hidden: bool
) -> None:  # fmt: skip
    ctx = await tenant(owner_sessionmaker)
    root = await run(owner_sessionmaker, ctx, timedelta(hours=1))
    sub = await run(owner_sessionmaker, ctx, None, parent=root)
    await failing(owner_sessionmaker, ctx["t"], kind, sub, state)
    found = await picked(dispatch_sessionmaker, "select run_id from orphan_subruns('1 minute', 100) "
                         "where tenant_id = :t", t=ctx["t"])  # fmt: skip
    assert found == ([] if hidden else [sub])


@pytest.mark.usefixtures("development_deployment")
@pytest.mark.parametrize(
    ("kind", "state", "hidden"), [*(("match", s, h) for s, h in CASES), ("dispatch", "held", False)]
)
async def test_matching_skips_an_event_its_failures_leave(
    owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, kind: str, state: str, hidden: bool
) -> None:  # fmt: skip
    """Its event attempts stay apart: they're the event's own, counted on its row."""
    t, endpoint_id = await endpoint(owner_sessionmaker)
    event = uuid.uuid4()
    await record(ingress_sessionmaker, endpoint_id, [(None, None, b"x")], ids=[event])
    await failing(owner_sessionmaker, t, kind, event, state)
    found = await picked(dispatch_sessionmaker, "select event_id from event_candidates(100, null, null) "
                         "where tenant_id = :t", t=t)  # fmt: skip
    assert found == ([] if hidden else [event])


async def test_a_passs_successes_clear_their_kinds_counts_by_tenant_and_item(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    """One statement for a pass: its kinds' rows of each (tenant, item) go; another kind's, and the same item id under
    another tenant, stay."""
    a, b = [await tenant(owner_sessionmaker) for _ in range(2)]
    item, other = uuid.uuid4(), uuid.uuid4()
    for ctx, kind, i in ((a, "reconcile_open", item), (a, "reconcile_slot", item), (a, "cancel", item),
                         (b, "reconcile_open", item), (a, "reconcile_open", other)):  # fmt: skip
        await failing(owner_sessionmaker, ctx["t"], kind, i, "held")
    async with dispatch_sessionmaker() as s, s.begin():
        gone = await s.execute(text("select work_failures_clear(:k, :t, :i)"),
                               {"k": ["reconcile_starting", "reconcile_open", "reconcile_slot"], "t": [a["t"]],
                                "i": [item]})  # fmt: skip
        assert gone.scalar_one() == 2
    async with owner_sessionmaker() as s:
        left = (await s.execute(text("select tenant_id, kind, item_id from work_failures where tenant_id = any(:t)"),
                                {"t": [a["t"], b["t"]]})).all()  # fmt: skip
    assert sorted(left) == sorted([(a["t"], "cancel", item), (b["t"], "reconcile_open", item),
                                   (a["t"], "reconcile_open", other)])  # fmt: skip
