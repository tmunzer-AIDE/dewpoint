# SPDX-License-Identifier: Apache-2.0
"""The deployment's ingress budget under load, on a real Temporal (the owner's ruling on 2b-4b's M3 checkpoint 4):
tenants of mixed fan-out at once, three sending steadily and one in bursts, against one deployment-wide limit, their
requests started by one dispatcher a cycle at a time on a versioned engine worker of the CLI dev server. Per tenant:
the deliveries admitted and refused (by outcome), its runs started and how fast, and from each accepted event's arrival
to its runs' starts at the median, the 95th percentile and the most, **measurements, never a guaranteed deadline**; and
the deployment's outstanding work sampled against its limit, which it must never pass, and its counters equal to the
truth at the end.

A probe, run by hand on a quiet machine, never in CI; bounded (`TRAFFIC_S`, then `DRAIN_S`). From `backend/`:

    DEWPOINT_PROBE=1 [DEWPOINT_PROBE_OUT=FILE] .venv/bin/pytest -p no:cacheprovider -n 0 -s \\
        tests/probes/test_ingress_budget_load.py

Numbers depend on the machine; record them with it."""

import asyncio
import json
import os
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.dispatcher import dispatch, main, matching
from dewpoint.apps.worker.store import DbRunStore
from tests.apps.dispatcher.inbound import bind, inbound, sealed
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.test_admission import KEYS, OPEN_GRAPH
from tests.apps.test_workflow_ops import create, publish
from tests.apps.worker.test_real_server import serving
from tests.core.ingress.support import RECORD
from tests.support.keys import FIXTURE_CONVERTER, FixtureKeys
from tests.support.temporal import start_local

pytestmark = [
    pytest.mark.skipif(not os.environ.get("DEWPOINT_PROBE"), reason="a probe, run by hand (DEWPOINT_PROBE)"),
    pytest.mark.usefixtures("development_deployment"),
]
# 30 starts a second, all of them for ingress, a 4 s wait: a limit of 120 requests outstanding, 101 of them for
# ingress (19 kept for top-ups). Endpoints' derived rates (30 over their bindings) stay above what each sends, so the
# budget alone refuses
CAPACITY = (30.0, 1.0, 4)
# Each tenant: (name, bindings, events a second sent steadily, bursts as (seconds in, events in one delivery)). With
# the three steady ones at their shares (101 over 4: 25 each), the bursty one finds 26 of room: its bursts of 20 and 24
# fit, its last, 60, doesn't while they hold theirs
TENANTS = (
    ("narrow", 1, 8.0, ()),
    ("middle", 5, 2.0, ()),
    ("wide", 10, 1.0, ()),
    ("bursty", 2, 0.0, ((10.0, 10), (20.0, 12), (30.0, 30))),
)
TRAFFIC_S = float(os.environ.get("DEWPOINT_PROBE_TRAFFIC_S", "40"))
DRAIN_S = float(os.environ.get("DEWPOINT_PROBE_DRAIN_S", "120"))
SAMPLE_S = 0.25
FAST = {  # the endpoints' own buckets never refuse: their derived event rates and the budget do
    "request_per_s": 1e6, "request_burst": 10**7, "event_per_s": 1e6, "event_burst": 10**7, "byte_per_s": 1e9,
    "byte_burst": 10**10,
}  # fmt: skip
PAYLOAD = {"type": "ap_down", "site": "lyon"}


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


def _pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))]


def _spread(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {"p50": round(_pct(values, 0.5), 2), "p95": round(_pct(values, 0.95), 2), "max": round(max(values), 2)}


async def _tenant(stack: tuple[Any, ...], bindings: int) -> Any:
    owner, api, admin, dispatch_, settings = stack
    ready = await inbound(owner, api, admin, dispatch_, settings)
    await bind(owner, ready)
    for n in range(bindings - 1):
        workflow = await create(api, ready.ctx, OPEN_GRAPH, name=f"fan-{n}")
        assert (await publish(api, ready.ctx, workflow, settings)).version is not None
        await bind(owner, ready, workflow)
    async with owner() as s, s.begin():
        await s.execute(text("insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, 1000)"),
                        {"t": ready.tenant_id})  # slots enough that only the dispatcher bounds its starts  # fmt: skip
        await s.execute(text("update webhook_endpoints set " + ", ".join(f"{k} = :{k}" for k in FAST)  # noqa: S608
                             + " where id = :e"), FAST | {"e": ready.endpoint_id})  # fmt: skip
        await s.execute(text("insert into tenant_event_counters (tenant_id, event_per_s, event_burst, event_tokens, "
                             "byte_per_s, byte_burst, byte_tokens) values (:t, 1e6, 10000000, 1e7, 1e9, 10000000000, "
                             "1e10) on conflict (tenant_id) do update set event_per_s = 1e6, event_burst = 10000000, "
                             "event_tokens = 1e7, byte_per_s = 1e9, byte_burst = 10000000000, byte_tokens = 1e10"),
                        {"t": ready.tenant_id})  # fmt: skip
    return ready


async def test_tenants_of_mixed_fan_out_steady_and_in_bursts_share_the_budget(
    server, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
    ingress_sessionmaker, api_settings,
) -> None:  # fmt: skip
    stack = (owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
    tenants = {name: await _tenant(stack, bindings) for name, bindings, _, _ in TENANTS}
    await workers(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update platform_settings set ingress_starts_per_s = :s, ingress_headroom = :h, "
                             "ingress_queue_wait_s = :w"), dict(zip("shw", CAPACITY, strict=True)))  # fmt: skip
        limit = (await s.execute(text("select ingress_limit()"))).scalar_one()
    outcomes: dict[str, Counter[str]] = {name: Counter() for name in tenants}
    accepted: dict[str, int] = Counter()
    began = time.monotonic()

    async def deliver(name: str, n: int) -> None:
        ready = tenants[name]
        ids = [uuid.uuid4() for _ in range(n)]
        params = {"e": ready.endpoint_id, "refusal": None, "read": 0, "ids": ids,
                  "sealed": [sealed(ready, i, PAYLOAD) for i in ids], "versions": [1] * n, "dedupe": [None] * n,
                  "digests": [None] * n}  # fmt: skip
        async with ingress_sessionmaker() as s, s.begin():  # ingress's own recording function, as its role calls it
            outcome = dict((await s.execute(RECORD, params)).scalar_one())
        outcomes[name][outcome["outcome"]] += 1
        if outcome["outcome"] == "recorded":
            accepted[name] += outcome["accepted"]

    async def steady(name: str, per_s: float) -> None:
        sent = 0
        while (elapsed := time.monotonic() - began) < TRAFFIC_S:
            due = int(elapsed * per_s) + 1 - sent
            for _ in range(max(0, due)):
                await deliver(name, 1)
                sent += 1
            await asyncio.sleep(1 / per_s / 2)

    async def bursts(name: str, at: tuple[tuple[float, int], ...]) -> None:
        for when, n in at:
            await asyncio.sleep(max(0.0, when - (time.monotonic() - began)))
            await deliver(name, n)

    samples: list[tuple[float, int, int]] = []
    sampling = True

    async def sample() -> None:
        while sampling:
            async with owner_sessionmaker() as s:
                outstanding, active = (await s.execute(text("select outstanding, active from ingress_budget"))).one()
            samples.append((round(time.monotonic() - began, 2), int(outstanding), int(active)))
            await asyncio.sleep(SAMPLE_S)

    rotation, busy, verified = dispatch.Rotation(), matching.Busy(), matching.Verified()
    dispatched: Counter[str] = Counter()
    left = text("select (select count(*) from run_requests where status in ('queued', 'starting')) + "
                "(select count(*) from inbound_events where status = 'pending')")  # fmt: skip
    traffic = [asyncio.create_task(steady(name, per_s)) for name, _, per_s, _ in TENANTS if per_s]
    traffic += [asyncio.create_task(bursts(name, at)) for name, _, _, at in TENANTS if at]
    sampler = asyncio.create_task(sample())
    async with serving(server.client, DbRunStore(worker_sessionmaker, FixtureKeys())):
        while time.monotonic() - began < TRAFFIC_S + DRAIN_S:
            async with owner_sessionmaker() as s, s.begin():  # the worker checks in, as a live one does (90 s window)
                await s.execute(text("update worker_instances set checked_at = statement_timestamp()"))
            dispatched.update({f"event_{k}": v for k, v in (await matching.match_once(
                dispatch_sessionmaker, KEYS, verified, busy=busy)).items()})  # fmt: skip
            dispatched.update(
                await dispatch.dispatch_once(dispatch_sessionmaker, server.client, KEYS, api_settings, BUILD, rotation)
            )
            if all(task.done() for task in traffic):
                async with owner_sessionmaker() as s:
                    if not (await s.execute(left)).scalar_one():
                        break
            await asyncio.sleep(main.CYCLE_S)
    elapsed = time.monotonic() - began
    sampling = False
    await sampler
    for task in traffic:
        task.cancel()
    async with owner_sessionmaker() as s:
        counted, actual = (await s.execute(text("select counted, actual from ingress_budget_drift()"))).one()
        per_tenant = {}
        for name, ready in tenants.items():
            waits = [float(w) for (w,) in (await s.execute(text(
                "select extract(epoch from r.started_at - e.received_at) from runs r "
                "join run_requests q on q.id = r.id join inbound_events e "
                "on q.idempotency_key like 'evt:' || e.id::text || ':%' "
                "where r.tenant_id = :t and r.started_at is not null"), {"t": ready.tenant_id})).all()]  # fmt: skip
            first, last = (await s.execute(text(
                "select extract(epoch from min(started_at)), extract(epoch from max(started_at)) from runs "
                "where tenant_id = :t"), {"t": ready.tenant_id})).one()  # fmt: skip
            span = float(last - first) if first is not None and last is not None and last > first else None
            per_tenant[name] = {
                "bindings": next(b for n, b, _, _ in TENANTS if n == name),
                "deliveries": dict(outcomes[name]), "events_accepted": accepted[name], "runs_started": len(waits),
                "starts_per_s": round(len(waits) / span, 2) if span else None,
                "accepted_to_start_s": _spread(waits),
            }  # fmt: skip
    peak = max((o for _, o, _ in samples), default=0)
    result = {
        "capacity": CAPACITY, "limit": limit, "traffic_s": TRAFFIC_S, "elapsed_s": round(elapsed, 1),
        "outstanding": {"max": peak, "mean": round(sum(o for _, o, _ in samples) / max(1, len(samples)), 1),
                        "samples": len(samples), "at_limit": sum(1 for _, o, _ in samples if o >= limit),
                        "most_active_tenants": max((a for *_, a in samples), default=0)},
        "dispatched": dict(dispatched), "tenants": per_tenant, "counted_actual_at_end": [int(counted), int(actual)],
    }  # fmt: skip
    out = os.environ.get("DEWPOINT_PROBE_OUT")
    if out:
        Path(out).write_text(json.dumps({"result": result, "samples": samples}, indent=1))  # noqa: ASYNC240
    print(json.dumps(result))
    assert peak <= limit, result  # the invariant: never past the limit
    assert counted == actual, result  # and the counters equal to the truth
