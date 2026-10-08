# SPDX-License-Identifier: Apache-2.0
"""Each of the leader's per-item passes counts an item's unexpected failures for its own kind of work (the owner's
rulings on the 2b-4b M3 design, rev 1 and 2): dispatch, the reconciler (by its request's phase), cancels, matching and
the sub-run pass. Seven in a row hold the item, with one alert, and the pass leaves it until an operator releases it.
A success clears its kind's count. Here the item's own work is a stand-in that fails or succeeds; the pick, the count,
the hold and the clearing are the real ones."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
import structlog
from sqlalchemy import text
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import cancels, dispatch, failures, matching, reconcile
from tests.apps.dispatcher.test_failure_candidates import in_phase, requested_cancel
from tests.core.ingress.support import endpoint, record
from tests.core.retention.support import request, run, sql, tenant

pytestmark = pytest.mark.usefixtures("development_deployment")


class Work:
    """The item's own work, as a pass calls it: each call counted; raising `failing` while it's set."""

    def __init__(self, outcome: str) -> None:
        self.outcome, self.calls = outcome, 0
        self.failing: BaseException | None = None

    async def __call__(self, *_a: Any, **_k: Any) -> str:
        self.calls += 1
        if self.failing is not None:
            raise self.failing
        return self.outcome


class Client:
    """Temporal as the passes see it here: a handle's cancel is the item's work."""

    namespace, data_converter = "default", None

    def __init__(self, work: Work) -> None:
        self.work = work

    def get_workflow_handle(self, *_a: Any, **_k: Any) -> Any:
        work = self.work

        class Handle:
            async def cancel(self, **_k: Any) -> None:
                await work()

        return Handle()


@dataclass
class Pass:
    kind: str
    work: tuple[Any, str] | None  # the module and name of the item's work, or None: the client's cancel
    outcome: str
    made: Callable[[Any, Any, dict[str, Any]], Awaitable[tuple[uuid.UUID, uuid.UUID]]]  # (tenant, item)
    once: Callable[[Any, Client], Awaitable[dict[str, int]]]
    again: str  # what makes the item due again for the pass's own recheck, beside its failure's delay


async def _queued(owner: Any, _ingress: Any, ctx: dict[str, Any]) -> tuple[uuid.UUID, uuid.UUID]:
    return ctx["t"], await request(owner, ctx, "queued", None)


def _phase(phase: str) -> Callable[[Any, Any, dict[str, Any]], Awaitable[tuple[uuid.UUID, uuid.UUID]]]:
    async def made(owner: Any, _ingress: Any, ctx: dict[str, Any]) -> tuple[uuid.UUID, uuid.UUID]:
        rid = await in_phase(owner, ctx, phase)
        await sql(owner, "update run_requests set starting_at = now() - interval '1 minute' where id = :i", i=rid)
        return ctx["t"], rid

    return made


async def _cancel(owner: Any, _ingress: Any, ctx: dict[str, Any]) -> tuple[uuid.UUID, uuid.UUID]:
    return ctx["t"], await requested_cancel(owner, ctx)


async def _event(owner: Any, ingress: Any, _ctx: dict[str, Any]) -> tuple[uuid.UUID, uuid.UUID]:
    t, endpoint_id = await endpoint(owner)
    event = uuid.uuid4()
    await record(ingress, endpoint_id, [(None, None, b"x")], ids=[event])
    return t, event


async def _orphan(owner: Any, _ingress: Any, ctx: dict[str, Any]) -> tuple[uuid.UUID, uuid.UUID]:
    root = await run(owner, ctx, timedelta(hours=1))
    return ctx["t"], await run(owner, ctx, None, parent=root)


PASSES = {
    "dispatch": Pass(failures.DISPATCH, (dispatch, "_dispatch"), "started", _queued,
                     lambda sm, c: dispatch.dispatch_once(sm, c, None, None, None), ""),  # type: ignore[arg-type]
    **{f"reconcile_{phase}": Pass(failures.RECONCILE[phase], (reconcile, f"_{phase}"), "ended", _phase(phase),
                                  lambda sm, c: reconcile.reconcile_once(sm, c, None, None),  # type: ignore[arg-type]
                                  "update run_requests set checked_at = null")
       for phase in ("starting", "open", "slot")},
    "cancel": Pass(failures.CANCEL, None, "sent", _cancel, lambda sm, c: cancels.send_cancels(sm, c), ""),  # type: ignore[arg-type]
    "match": Pass(failures.MATCH, (matching, "match_event"), "matched", _event,
                  lambda sm, c: matching.match_once(sm, None, matching.Verified()), ""),  # type: ignore[arg-type]
    "subrun": Pass(failures.SUBRUN, (reconcile, "_subrun"), "ended", _orphan,
                   lambda sm, c: reconcile.reconcile_subruns(sm, c), "update runs set next_check_at = null"),  # type: ignore[arg-type]
}  # fmt: skip


@pytest.fixture
def stand_in(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> tuple[Pass, Work, Client]:
    spec = PASSES[request.param]
    work = Work(spec.outcome)
    if spec.work is not None:
        monkeypatch.setattr(*spec.work, work)
    return spec, work, Client(work)


async def count(owner: Any, kind: str, item: uuid.UUID) -> tuple[Any, ...] | None:
    async with owner() as s:
        found = await s.execute(text("select errors, held_at is not null from work_failures where kind = :k "
                                     "and item_id = :i"), {"k": kind, "i": item})  # fmt: skip
        row = found.first()
    return tuple(row) if row is not None else None


async def due(owner: Any, spec: Pass) -> None:
    """The failure's delay past (a test doesn't wait minutes), and the pass's own recheck."""
    await sql(owner, "update work_failures set due_at = now() - interval '1 second'")
    if spec.again:
        await sql(owner, spec.again)


@pytest.mark.parametrize("stand_in", PASSES, indirect=True)
async def test_seven_failures_in_a_row_hold_the_item_for_its_pass_alerting_once(
    owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, stand_in
) -> None:  # fmt: skip
    spec, work, client = stand_in
    tenant_id, item = await spec.made(owner_sessionmaker, ingress_sessionmaker, await tenant(owner_sessionmaker))
    work.failing = RuntimeError("a bug")
    seen = []
    with structlog.testing.capture_logs() as logs:
        for _ in range(failures.BOUND):
            await spec.once(dispatch_sessionmaker, client)
            seen.append(await count(owner_sessionmaker, spec.kind, item))
            await due(owner_sessionmaker, spec)
        assert work.calls == failures.BOUND
        await spec.once(dispatch_sessionmaker, client)
    assert seen == [(n, n == failures.BOUND) for n in range(1, failures.BOUND + 1)]
    assert work.calls == failures.BOUND  # held: never tried again
    assert [e["event"] for e in logs if e["event"].endswith("_held")] == [f"{spec.kind}_held"]
    assert tenant_id is not None


@pytest.mark.parametrize("stand_in", PASSES, indirect=True)
async def test_a_success_clears_its_kinds_count_and_only_its_own(
    owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, stand_in
) -> None:  # fmt: skip
    """A reconciliation's success clears its request's counts of every phase."""
    spec, work, client = stand_in
    tenant_id, item = await spec.made(owner_sessionmaker, ingress_sessionmaker, await tenant(owner_sessionmaker))
    other = failures.SUBRUN if spec.kind != failures.SUBRUN else failures.DISPATCH
    for kind in (spec.kind, other):
        await sql(owner_sessionmaker, "insert into work_failures (tenant_id, kind, item_id, errors, last_error, "
                  "due_at) values (:t, :k, :i, 3, 'RuntimeError', now() - interval '1 second')", t=tenant_id, k=kind,
                  i=item)  # fmt: skip
    await spec.once(dispatch_sessionmaker, client)
    assert work.calls == 1
    assert await count(owner_sessionmaker, spec.kind, item) is None
    assert await count(owner_sessionmaker, other, item) == (3, False)


@pytest.mark.parametrize("stand_in", ["cancel"], indirect=True)
@pytest.mark.parametrize(
    ("error", "counted"),
    [
        (RPCError("refused", RPCStatusCode.PERMISSION_DENIED, b""), True),
        (RuntimeError("a bug"), True),
        (RPCError("down", RPCStatusCode.UNAVAILABLE, b""), False),
        (RPCError("gone, or the namespace isn't answering", RPCStatusCode.NOT_FOUND, b""), False),
    ],
    ids=["refused", "bug", "unanswered", "not_found_unconfirmed"],
)
async def test_a_cancel_that_fails_to_send_is_counted_unless_temporals_answer_is_uncertain(
    owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, stand_in, monkeypatch, error, counted
) -> None:  # fmt: skip
    spec, work, client = stand_in
    _, item = await spec.made(owner_sessionmaker, ingress_sessionmaker, await tenant(owner_sessionmaker))

    async def unanswered(_client: Any) -> bool:
        return False

    monkeypatch.setattr(cancels, "namespace_answers", unanswered)
    work.failing = error
    assert await spec.once(dispatch_sessionmaker, client) == {"unsent": 1}
    assert await count(owner_sessionmaker, spec.kind, item) == ((1, False) if counted else None)


@pytest.mark.parametrize("stand_in", ["cancel"], indirect=True)
async def test_a_held_cancel_stays_requested_and_is_never_shown_sent(
    owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, stand_in
) -> None:  # fmt: skip
    spec, work, client = stand_in
    _, item = await spec.made(owner_sessionmaker, ingress_sessionmaker, await tenant(owner_sessionmaker))
    work.failing = RPCError("refused", RPCStatusCode.PERMISSION_DENIED, b"")
    for _ in range(failures.BOUND + 1):
        await spec.once(dispatch_sessionmaker, client)
        await due(owner_sessionmaker, spec)
    assert await count(owner_sessionmaker, spec.kind, item) == (failures.BOUND, True)
    async with owner_sessionmaker() as s:
        found = await s.execute(text("select cancel_requested_at is not null, cancel_sent_at is null from run_requests "
                                     "where id = :i"), {"i": item})  # fmt: skip
        assert tuple(found.one()) == (True, True)


@pytest.mark.parametrize("stand_in", ["reconcile_open"], indirect=True)
async def test_a_reconcile_failure_counts_in_its_phase_and_a_success_in_the_next_clears_it(
    owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, stand_in, monkeypatch
) -> None:  # fmt: skip
    """The owner's ruling (rev 2): starting, then open: the starting phase's count is apart, and the open phase's
    success clears it."""
    spec, work, client = stand_in
    starting = Work("started")
    starting.failing = RuntimeError("a bug")
    monkeypatch.setattr(reconcile, "_starting", starting)
    tenant_id, item = await _phase("starting")(owner_sessionmaker, ingress_sessionmaker,
                                               await tenant(owner_sessionmaker))  # fmt: skip
    await spec.once(dispatch_sessionmaker, client)
    assert await count(owner_sessionmaker, failures.RECONCILE["starting"], item) == (1, False)
    await sql(owner_sessionmaker, "update run_requests set status = 'started', checked_at = null where id = :i", i=item)
    await run(owner_sessionmaker, {"t": tenant_id, **await _workflow(owner_sessionmaker, item)}, None, run_id=item)
    await spec.once(dispatch_sessionmaker, client)
    assert work.calls == 1
    assert await count(owner_sessionmaker, failures.RECONCILE["starting"], item) is None


async def _workflow(owner: Any, request_id: uuid.UUID) -> dict[str, Any]:
    async with owner() as s:
        found = await s.execute(text("select workflow_id, workflow_version_id from run_requests where id = :i"),
                                {"i": request_id})  # fmt: skip
        w, v = found.one()
    return {"w": w, "v": v}
