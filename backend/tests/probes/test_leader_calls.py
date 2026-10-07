# SPDX-License-Identifier: Apache-2.0
"""The leader's Temporal calls' probe (the 2b-4b plan's M1b; the owner's D16): each leader pass, its calls and its time
per item, driven against Temporal's CLI dev server (real time) with a backlog of 1, 10 and 50 items; the whole cycle
with every pass's backlog full; `keys retire`'s proof at 10, 100 and 1,000 executions; and a closed execution's
history read at 1,000 and 5,000 events. Since the owner's D16 ruling, also each item's worst shapes: run evidence
over long histories, a schedule with many incarnations (its misses, its tombstone, its strays found in Temporal),
dispatch's starts and matching's events (every dispatcher's, every cycle), and a whole cycle with all of them.
Every call to Temporal is timed where the SDK makes it (`ServiceClient._rpc_call`), with the deadline it carried, if
any. A run by hand, never in CI (skipped unless `DEWPOINT_PROBE` is set); its results go to `DEWPOINT_PROBE_OUT`
(JSON). From `backend/`:

    DEWPOINT_PROBE=1 DEWPOINT_PROBE_OUT=leader.json .venv/bin/pytest tests/probes/test_leader_calls.py -p no:randomly

These numbers are the dev server's on this machine: they set the provisional budgets at M1, which M4's D12 server
revalidates (the owner's D16); a fake's latency never sets one."""

import contextlib
import json
import os
import statistics
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps import schedules
from dewpoint.apps.dispatcher import cancels, dispatch, evidence, matching, reconcile, schedule_sync
from dewpoint.apps.dispatcher.recount import recount_once
from dewpoint.core.db import tenant_scope
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.dispatcher.inbound import bind, inbound, sealed
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.test_admission import KEYS, TOKEN, admit, current, published
from tests.core.ingress.support import RECORD
from tests.core.retention.support import request, run, sql, tenant
from tests.probes.ingress_load import FAST
from tests.support.keys import FIXTURE_CONVERTER

pytestmark = [
    pytest.mark.skipif(not os.environ.get("DEWPOINT_PROBE"), reason="a probe, run by hand (DEWPOINT_PROBE)"),
    pytest.mark.usefixtures("development_deployment"),
]
SIZES = (1, 10, 50)
QUEUE = "probe-nowhere"  # no worker polls it: an execution started there stays as the probe leaves it
TIMING = {"cron": None, "every_s": 3600, "offset_s": 0, "time_zone": "UTC", "catchup_window_s": 600}
RETENTION = timedelta(days=1)
RESULTS: list[dict[str, Any]] = []


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment
    out = os.environ.get("DEWPOINT_PROBE_OUT")
    if out:
        Path(out).write_text(json.dumps(RESULTS, indent=1))  # noqa: ASYNC240  # once, at the module's end


class Calls:
    """Every call the SDK makes to Temporal while watched: its RPC, the deadline it carried (None: none), its time."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, float | None, float, bool]] = []

    @contextlib.contextmanager
    def watching(self, client: Client) -> Iterator["Calls"]:
        cls = type(client.service_client)
        original = cls._rpc_call
        rows = self.rows

        async def timed(self_: Any, rpc: str, req: Any, resp_type: Any, **kw: Any) -> Any:
            t0, ok = time.monotonic(), True
            try:
                return await original(self_, rpc, req, resp_type, **kw)
            except Exception:
                ok = False
                raise
            finally:
                deadline = kw.get("timeout")
                rows.append((rpc, None if deadline is None else deadline.total_seconds(), time.monotonic() - t0, ok))

        cls._rpc_call = timed  # type: ignore[method-assign]
        try:
            yield self
        finally:
            cls._rpc_call = original  # type: ignore[method-assign]

    def summary(self) -> dict[str, Any]:
        by: dict[str, list[tuple[float | None, float, bool]]] = {}
        for rpc, deadline, took, ok in self.rows:
            by.setdefault(rpc, []).append((deadline, took, ok))
        return {
            rpc: {"calls": len(v), "no_deadline": sum(d is None for d, _, _ in v),
                  "failed": sum(not ok for *_, ok in v),
                  "median_ms": round(statistics.median(t for _, t, _ in v) * 1000, 2),
                  "max_ms": round(max(t for _, t, _ in v) * 1000, 2),
                  "deadlines_s": sorted({d for d, _, _ in v if d is not None})}
            for rpc, v in sorted(by.items())
        }  # fmt: skip


async def measured(name: str, n: int, client: Client, run_pass: Callable[[], Awaitable[Any]]) -> dict[str, Any]:
    calls = Calls()
    with calls.watching(client):
        t0 = time.monotonic()
        outcome = await run_pass()
        took = time.monotonic() - t0
    row = {"pass": name, "items": n, "outcome": outcome, "seconds": round(took, 3),
           "per_item_ms": round(took / max(n, 1) * 1000, 2), "calls": calls.summary()}  # fmt: skip
    RESULTS.append(row)
    return row


async def target(client: Client, workflow_id: str, *, closed: bool, signals: int = 0) -> None:
    """An execution under `workflow_id`, on a queue no worker polls: left open, or terminated (`signals` signals in
    its history first)."""
    handle = await client.start_workflow("ProbeTarget", id=workflow_id, task_queue=QUEUE)
    for i in range(signals):
        await handle.signal("probe", i)
    if closed:
        await handle.terminate()


# --- the reconciler's passes -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("n", SIZES)
async def test_reconciler_open_runs(n, server, owner_sessionmaker, dispatch_sessionmaker, api_settings) -> None:
    """Started requests whose row is still running, their executions terminated: a describe each, then the end."""
    ctx = await tenant(owner_sessionmaker)
    for _ in range(n):
        rid = await request(owner_sessionmaker, ctx, "started", None)
        await run(owner_sessionmaker, ctx, None, run_id=rid)
        await target(server.client, run_workflow_id(str(ctx["t"]), str(rid)), closed=True)
    row = await measured(
        "reconciler_open_runs",
        n,
        server.client,
        lambda: reconcile.reconcile_once(dispatch_sessionmaker, server.client, KEYS, api_settings),
    )
    assert row["outcome"] == {"ended": n}


async def _orphans(owner: Any, client: Client, n: int) -> None:
    ctx = await tenant(owner)
    root = await run(owner, ctx, timedelta(minutes=5))
    for _ in range(n):
        sub = await run(owner, ctx, None, parent=root)
        await target(client, run_workflow_id(str(ctx["t"]), str(sub)), closed=True)


@pytest.mark.parametrize("n", SIZES)
async def test_reconciler_subruns(n, server, owner_sessionmaker, dispatch_sessionmaker) -> None:
    """Sub-runs a root's close left running (#48), their executions terminated: a describe each, then the end."""
    await _orphans(owner_sessionmaker, server.client, n)
    row = await measured(
        "reconciler_subruns",
        n,
        server.client,
        lambda: reconcile.reconcile_subruns(dispatch_sessionmaker, server.client),
    )
    assert row["outcome"] == {"ended": n}


async def _cancellable(owner: Any, client: Client, n: int) -> None:
    ctx = await tenant(owner)
    for _ in range(n):
        rid = await request(owner, ctx, "started", None)
        await run(owner, ctx, None, run_id=rid)
        await sql(owner, "update run_requests set cancel_requested_at = now() where id = :i", i=rid)
        await target(client, run_workflow_id(str(ctx["t"]), str(rid)), closed=False)


@pytest.mark.parametrize("n", SIZES)
async def test_cancels(n, server, owner_sessionmaker, dispatch_sessionmaker) -> None:
    """Running runs with a cancel to send: a cancel each."""
    await _cancellable(owner_sessionmaker, server.client, n)
    row = await measured(
        "cancels", n, server.client, lambda: cancels.send_cancels(dispatch_sessionmaker, server.client)
    )
    assert sum(row["outcome"].values()) == n


# --- the schedule passes ----------------------------------------------------------------------------------------------


class Leading:
    async def leading(self) -> bool:
        return True


async def _schedules(n: int, owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any) -> None:
    ctx, wf = await published(owner, api, admin, settings)
    await current(dispatch)
    async with api() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        for _ in range(n):
            await schedules.create(s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
                                   timing=TIMING, mode="live", input={"token": TOKEN}, enabled=True)  # fmt: skip


@pytest.mark.parametrize("n", SIZES)
async def test_schedule_sync_then_misses(
    n, server, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """New schedules synced (each created paused, read back and unpaused), then their misses read (a describe each)."""
    await _schedules(n, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
    await measured(
        "schedule_sync",
        n,
        server.client,
        lambda: schedule_sync.sync_schedules(dispatch_sessionmaker, server.client, Leading()),
    )
    await sql(owner_sessionmaker, "update schedules set misses_checked_at = null")
    await measured("misses", n, server.client, lambda: schedule_sync.check_misses(dispatch_sessionmaker, server.client))


@pytest.mark.parametrize("n", SIZES)
async def test_strays(n, server, owner_sessionmaker, dispatch_sessionmaker) -> None:
    """Incarnations that aren't current, none of them in Temporal any more: a describe each (not found)."""
    ctx = await tenant(owner_sessionmaker)
    for _ in range(n):
        await sql(owner_sessionmaker, "insert into schedule_incarnations (temporal_id, tenant_id, schedule_id, number) "
                  "values (:i, :t, :s, 1)", i=f"t:{ctx['t']}:sched:{uuid.uuid4()}~1", t=ctx["t"],
                  s=uuid.uuid4())  # fmt: skip
    row = await measured("strays", n, server.client, lambda: schedule_sync.check_strays(dispatch_sessionmaker,
                                                                                         server.client))  # fmt: skip
    assert sum(row["outcome"].values()) == n


# --- run evidence and its proof ---------------------------------------------------------------------------------------


async def _evidence(owner: Any, client: Client, n: int, *, signals: int = 0) -> dict[str, Any]:
    ctx = await tenant(owner)
    for _ in range(n):
        workflow_id = run_workflow_id(str(ctx["t"]), str(uuid.uuid4()))
        await target(client, workflow_id, closed=True, signals=signals)
        await sql(owner, "insert into execution_evidence (tenant_id, workflow_id, started_at) "
                  "values (:t, :w, now() - interval '1 hour')", t=ctx["t"], w=workflow_id)  # fmt: skip
    return ctx


@pytest.mark.parametrize("n", SIZES)
async def test_run_evidence(n, server, owner_sessionmaker, dispatch_sessionmaker) -> None:
    """Due rows, each a closed execution: a describe, then its whole history."""
    await _evidence(owner_sessionmaker, server.client, n)
    await measured(
        "run_evidence",
        n,
        server.client,
        lambda: evidence.check_evidence(dispatch_sessionmaker, server.client, retention=RETENTION),
    )


@pytest.mark.parametrize("n", (10, 100, 1_000))
async def test_keys_retire_proof(n, server, owner_sessionmaker, admin_sessionmaker) -> None:
    """`keys retire`'s proof over a tenant's executions with evidence (a dry run: nothing recorded)."""
    ctx = await _evidence(owner_sessionmaker, server.client, n)

    async def prove() -> Any:
        async with admin_sessionmaker() as s, s.begin():
            await tenant_scope(s, ctx["t"])
            found = await evidence.prove(s, server.client, ctx["t"], before=None, record=False)
            return {"retained": found.retained, "unread": found.unread, "lost": found.lost, "pending": found.pending}

    await measured("keys_retire_proof", n, server.client, prove)


@pytest.mark.parametrize("events", (1_000, 5_000))
async def test_history_read(events, server) -> None:
    """A closed execution's whole history, read page by page, at `events` signals."""
    workflow_id = run_workflow_id(str(uuid.uuid4()), str(uuid.uuid4()))  # a tenant's: the codec seals its signals
    await target(server.client, workflow_id, closed=True, signals=events)
    described = await server.client.get_workflow_handle(workflow_id).describe()

    async def read() -> dict[str, Any]:
        found = await evidence._history(server.client, workflow_id, described.run_id)
        return {"children": len(found.children)}

    await measured("history_read", events, server.client, read)


# --- each item's worst shapes (the owner's D16 ruling) ----------------------------------------------------------------


@pytest.mark.parametrize("events", (1_000, 5_000))
async def test_run_evidence_long_histories(events, server, owner_sessionmaker, dispatch_sessionmaker) -> None:
    """Five due rows, each a closed execution of `events` events: a describe, then its whole history, 250 events a
    page (Temporal's limit is 51,200 events, about 205 pages)."""
    await _evidence(owner_sessionmaker, server.client, 5, signals=events)
    await measured(
        f"run_evidence_{events}_events",
        5,
        server.client,
        lambda: evidence.check_evidence(dispatch_sessionmaker, server.client, retention=RETENTION),
    )


async def _incarnated(k: int, owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any, client: Client) -> Any:
    """A schedule synced (its first incarnation, number 1, created in Temporal), then `k - 1` later incarnations
    recorded that never landed: its id and tenant."""
    await _schedules(1, owner, api, admin, dispatch, settings)
    async with owner() as s:
        tenant_id, schedule_id = (await s.execute(text(
            "select tenant_id, id from schedules order by created_at desc, id limit 1"))).one()  # fmt: skip
    await schedule_sync.sync_one(dispatch, client, Leading(), tenant_id, schedule_id)
    for number in range(2, k + 1):
        await sql(owner, "insert into schedule_incarnations (temporal_id, tenant_id, schedule_id, number) "
                  "values (:i, :t, :s, :n)", i=schedule_sync.incarnation_id(tenant_id, schedule_id, number),
                  t=tenant_id, s=schedule_id, n=number)  # fmt: skip
    return tenant_id, schedule_id


@pytest.mark.parametrize("k", (1, 5, 20))
async def test_incarnations(
    k, server, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """One schedule with `k` incarnations: its misses read (a describe each), then, deleted, its tombstone synced (each
    described; the one found paused, its count read, and deleted)."""
    tenant_id, schedule_id = await _incarnated(k, owner_sessionmaker, api_sessionmaker, admin_sessionmaker,
                                               dispatch_sessionmaker, api_settings, server.client)  # fmt: skip
    await sql(owner_sessionmaker, "update schedules set misses_checked_at = null")
    await sql(owner_sessionmaker, "update schedules set misses_checked_at = now() where id <> :s", s=schedule_id)
    await measured(f"misses_{k}_incarnations", 1, server.client,
                   lambda: schedule_sync.check_misses(dispatch_sessionmaker, server.client))  # fmt: skip
    await sql(owner_sessionmaker, "update schedules set input = null, deleted_at = now() - interval '1 minute', "
              "generation = generation + 1, updated_at = now() where id = :s", s=schedule_id)  # fmt: skip
    await measured(f"tombstone_{k}_incarnations", 1, server.client,
                   lambda: schedule_sync.sync_one(dispatch_sessionmaker, server.client, Leading(), tenant_id,
                                                  schedule_id))  # fmt: skip


async def _strays_found(n: int, owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any, client: Client) -> None:
    """`n` schedules each with a stray in Temporal: its first incarnation, synced, then a second recorded as current."""
    for _ in range(n):
        tenant_id, schedule_id = await _incarnated(2, owner, api, admin, dispatch, settings, client)
        await sql(owner, "update schedule_incarnations set checked_at = null where schedule_id = :s", s=schedule_id)


@pytest.mark.parametrize("n", SIZES)
async def test_strays_found(
    n, server, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Strays still in Temporal: a describe each, then paused, counted and deleted."""
    await _strays_found(n, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                        api_settings, server.client)  # fmt: skip
    await measured("strays_found", n, server.client,
                   lambda: schedule_sync.check_strays(dispatch_sessionmaker, server.client))  # fmt: skip


async def _queued(n: int, owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any) -> None:
    """`n` tenants, each with a request due: one start each."""
    await current(dispatch)
    await workers(owner)
    for _ in range(n):
        ctx, wf = await published(owner, api, admin, settings)
        await admit(api, ctx, wf)


@pytest.mark.parametrize("n", SIZES)
async def test_dispatch(
    n, server, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Due requests of `n` tenants, every dispatcher's each cycle: a start each, on a queue no worker polls."""
    await _queued(n, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
    row = await measured("dispatch", n, server.client, lambda: dispatch.dispatch_once(
        dispatch_sessionmaker, server.client, KEYS, api_settings, BUILD, dispatch.Rotation()))  # fmt: skip
    assert row["outcome"] == {"started": n}


async def _events(n: int, owner: Any, api: Any, admin: Any, dispatch_: Any, ingress: Any, settings: Any) -> None:
    """`n` sealed events pending on an endpoint bound to one workflow, its buckets never refusing."""
    ready = await inbound(owner, api, admin, dispatch_, settings)
    await bind(owner, ready)
    async with owner() as s, s.begin():
        await s.execute(text("update webhook_endpoints set " + ", ".join(f"{k} = :{k}" for k in FAST)  # noqa: S608
                             + " where id = :e"), FAST | {"e": ready.endpoint_id})  # fmt: skip
    ids = [uuid.uuid4() for _ in range(n)]
    params = {"e": ready.endpoint_id, "refusal": None, "read": 0, "ids": ids,
              "sealed": [sealed(ready, i, {"type": "ap_down", "pad": "x" * 500}) for i in ids],
              "versions": [1] * n, "dedupe": [None] * n, "digests": [None] * n}  # fmt: skip
    async with ingress() as s, s.begin():
        await s.execute(RECORD, params)


@pytest.mark.parametrize("n", SIZES)
async def test_matching(
    n, server, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, ingress_sessionmaker,
    api_settings,
) -> None:  # fmt: skip
    """Pending events, every dispatcher's each cycle: each opened, matched to its binding and its request admitted
    (no Temporal call: the database's and the codec's time)."""
    await _events(n, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                  ingress_sessionmaker, api_settings)  # fmt: skip
    row = await measured("matching", n, server.client,
                         lambda: matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()))  # fmt: skip
    assert row["outcome"].get("matched") == n, row["outcome"]


# --- the whole cycle --------------------------------------------------------------------------------------------------


async def test_whole_cycle(
    server, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Every leader pass with a backlog of 50, in the dispatcher's order (main.py), one cycle."""
    full = 50
    ctx = await tenant(owner_sessionmaker)
    for _ in range(full):
        rid = await request(owner_sessionmaker, ctx, "started", None)
        await run(owner_sessionmaker, ctx, None, run_id=rid)
        await target(server.client, run_workflow_id(str(ctx["t"]), str(rid)), closed=True)
    await _orphans(owner_sessionmaker, server.client, full)
    await _cancellable(owner_sessionmaker, server.client, full)
    await _schedules(full, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                     api_settings)  # fmt: skip
    await _evidence(owner_sessionmaker, server.client, full)

    async def cycle() -> dict[str, Any]:
        done: dict[str, Any] = {}
        for name, step in (
            ("reconcile", lambda: reconcile.reconcile_once(dispatch_sessionmaker, server.client, KEYS, api_settings)),
            ("subruns", lambda: reconcile.reconcile_subruns(dispatch_sessionmaker, server.client)),
            ("cancels", lambda: cancels.send_cancels(dispatch_sessionmaker, server.client)),
            ("sync", lambda: schedule_sync.sync_schedules(dispatch_sessionmaker, server.client, Leading())),
            ("misses", lambda: schedule_sync.check_misses(dispatch_sessionmaker, server.client)),
            ("strays", lambda: schedule_sync.check_strays(dispatch_sessionmaker, server.client)),
            ("evidence", lambda: evidence.check_evidence(dispatch_sessionmaker, server.client, retention=RETENTION)),
        ):
            t0 = time.monotonic()
            outcome = await step()
            done[name] = {"outcome": outcome, "seconds": round(time.monotonic() - t0, 3)}
        return done

    await measured("whole_cycle", full, server.client, cycle)


async def test_whole_cycle_worst_shapes(
    server, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, ingress_sessionmaker,
    api_settings,
) -> None:  # fmt: skip
    """A cycle as `main.cycle` runs it, but for its observe and its reports (the dev server's build is BUILD): dispatch
    and matching, then every leader pass, each backlog at 50, in its worst shape here: evidence over histories of 1,000
    events, schedules with 5 incarnations to read misses of, strays found in Temporal."""
    full = 50
    await _queued(full, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
    await _events(full, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                  ingress_sessionmaker, api_settings)  # fmt: skip
    ctx = await tenant(owner_sessionmaker)
    for _ in range(full):
        rid = await request(owner_sessionmaker, ctx, "started", None)
        await run(owner_sessionmaker, ctx, None, run_id=rid)
        await target(server.client, run_workflow_id(str(ctx["t"]), str(rid)), closed=True)
    await _orphans(owner_sessionmaker, server.client, full)
    await _cancellable(owner_sessionmaker, server.client, full)
    await _strays_found(full, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                        api_settings, server.client)  # fmt: skip
    incarnated = [
        (
            await _incarnated(
                5,
                owner_sessionmaker,
                api_sessionmaker,
                admin_sessionmaker,
                dispatch_sessionmaker,
                api_settings,
                server.client,
            )
        )[1]
        for _ in range(full)
    ]
    await _schedules(full, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                     api_settings)  # fmt: skip  # new ones, queued for their sync
    long = await _evidence(owner_sessionmaker, server.client, full, signals=1_000)
    # Only the worst shapes due: the misses of the schedules of 5 incarnations (their earlier ones not strays yet), the
    # strays found in Temporal, the evidence of the long histories (not that of the runs made above)
    await sql(owner_sessionmaker, "update schedules set misses_checked_at = case when id = any(:ids) then null "
              "else now() end", ids=incarnated)  # fmt: skip
    await sql(owner_sessionmaker, "update schedule_incarnations set checked_at = now() where schedule_id = any(:ids)",
              ids=incarnated)  # fmt: skip
    await sql(owner_sessionmaker, "update execution_evidence set next_check_at = now() + interval '1 day' "
              "where tenant_id <> :t", t=long["t"])  # fmt: skip

    async def cycle() -> dict[str, Any]:
        done: dict[str, Any] = {}
        for name, step in (
            ("dispatch", lambda: dispatch.dispatch_once(dispatch_sessionmaker, server.client, KEYS, api_settings, BUILD,
                                                        dispatch.Rotation())),
            ("matching", lambda: matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified())),
            ("reconcile", lambda: reconcile.reconcile_once(dispatch_sessionmaker, server.client, KEYS, api_settings)),
            ("subruns", lambda: reconcile.reconcile_subruns(dispatch_sessionmaker, server.client)),
            ("cancels", lambda: cancels.send_cancels(dispatch_sessionmaker, server.client)),
            ("sync", lambda: schedule_sync.sync_schedules(dispatch_sessionmaker, server.client, Leading())),
            ("misses", lambda: schedule_sync.check_misses(dispatch_sessionmaker, server.client)),
            ("strays", lambda: schedule_sync.check_strays(dispatch_sessionmaker, server.client)),
            ("retention", lambda: evidence.Retention()(server.client)),
            ("evidence", lambda: evidence.check_evidence(dispatch_sessionmaker, server.client, retention=RETENTION)),
            ("recount", lambda: recount_once(dispatch_sessionmaker)),
        ):  # fmt: skip
            calls = Calls()
            with calls.watching(server.client):
                t0 = time.monotonic()
                outcome = await step()
            done[name] = {"outcome": outcome if isinstance(outcome, dict) else str(outcome),
                          "seconds": round(time.monotonic() - t0, 3),
                          "calls": sum(v["calls"] for v in calls.summary().values())}  # fmt: skip
        return done

    await measured("whole_cycle_worst_shapes", full, server.client, cycle)
