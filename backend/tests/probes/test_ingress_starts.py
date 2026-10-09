# SPDX-License-Identifier: Apache-2.0
"""Ingress's rates against a real Temporal (the 2b-4b plan's M3, item 7; D8, D9): a backlog of events matched, each
event's requests started on a versioned engine worker of the CLI dev server, and their runs ended, at fan-outs 1 and 20,
every other limit at its default (5 runs at once a tenant; a tenant's due requests a round at a time, for up to
`dispatch.AGAIN_S` a cycle: the owner's ruling 1 on the M3 checkpoint). One dispatcher, a cycle at a time (its
matching, its dispatch, then its one-second sleep), not the leader (each run's own end write frees its slot). Per event
and binding: from the event's arrival to its run's start, and to its end; and the dispatch passes' own time, what they
counted (`no_slot`: a tenant at its 5 runs), and their time per start.

A probe, run by hand on a quiet machine, never in CI; each case is bounded (`DEADLINE_S`). From `backend/`:

    DEWPOINT_PROBE=1 [DEWPOINT_PROBE_OUT=FILE] .venv/bin/pytest -p no:cacheprovider -n 0 -s \\
        tests/probes/test_ingress_starts.py

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
from tests.support.temporal import probe_temporal

pytestmark = [
    pytest.mark.skipif(not os.environ.get("DEWPOINT_PROBE"), reason="a probe, run by hand (DEWPOINT_PROBE)"),
    pytest.mark.usefixtures("development_deployment"),
]
# (bindings an endpoint, events, the tenant's runs at once: None for the default, 5, the ingress capacity: None for
# none set): 200 runs a case but the last; slots enough in the last two that only the dispatcher bounds the starts
CASES = (
    (1, 200, None, None),
    (20, 10, None, None),
    (20, 10, 1_000, None),
    (20, 5, 1_000, (8.0, 0.5, 30)),
)  # the last limited: (starts, headroom, wait) give the deployment a limit of 120, 101 for ingress: 5 events of 20
DEADLINE_S = float(os.environ.get("DEWPOINT_PROBE_DEADLINE_S", "300"))
FAST = {  # the endpoint's and the tenant's buckets never refuse: the backlog is recorded at once
    "request_per_s": 1e6, "request_burst": 10**7, "event_per_s": 1e6, "event_burst": 10**7, "byte_per_s": 1e9,
    "byte_burst": 10**10,
}  # fmt: skip
RESULTS: list[dict[str, Any]] = []


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    # a dev server of its own, or the external one DEWPOINT_PROBE_TEMPORAL_ADDRESS names (2b-4b M4: the D12 server)
    async with probe_temporal(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment
    out = os.environ.get("DEWPOINT_PROBE_OUT")
    if out:
        Path(out).write_text(json.dumps(RESULTS, indent=1))  # noqa: ASYNC240  # once, at the module's end


def _pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))]


@pytest.mark.parametrize(("fan_out", "events", "limit", "capacity"), CASES)
async def test_a_backlog_of_events_becomes_runs_on_a_real_temporal(
    server, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
    api_settings, fan_out: int, events: int, limit: int | None, capacity: tuple[float, float, int] | None,
) -> None:  # fmt: skip
    ready = await inbound(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
    await bind(owner_sessionmaker, ready)
    for n in range(fan_out - 1):
        workflow = await create(api_sessionmaker, ready.ctx, OPEN_GRAPH, name=f"fan-{n}")
        assert (await publish(api_sessionmaker, ready.ctx, workflow, api_settings)).version is not None
        await bind(owner_sessionmaker, ready, workflow)
    await workers(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        if capacity is not None:  # the owner's ruling on the M3 checkpoint 4: the deployment's limit
            await s.execute(text("update platform_settings set ingress_starts_per_s = :s, ingress_headroom = :h, "
                                 "ingress_queue_wait_s = :w"), dict(zip("shw", capacity, strict=True)))  # fmt: skip
        if limit is not None:
            await s.execute(text("insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, :n)"),
                            {"t": ready.tenant_id, "n": limit})  # fmt: skip
        await s.execute(text("update webhook_endpoints set " + ", ".join(f"{k} = :{k}" for k in FAST)  # noqa: S608
                             + " where id = :e"), FAST | {"e": ready.endpoint_id})  # fmt: skip
        await s.execute(text("insert into tenant_event_counters (tenant_id, event_per_s, event_burst, event_tokens, "
                             "byte_per_s, byte_burst, byte_tokens) values (:t, 1e6, 10000000, 1e7, 1e9, 10000000000, "
                             "1e10) on conflict (tenant_id) do update set event_per_s = 1e6, event_burst = 10000000, "
                             "event_tokens = 1e7, byte_per_s = 1e9, byte_burst = 10000000000, byte_tokens = 1e10"),
                        {"t": ready.tenant_id})  # fmt: skip
    ids = [uuid.uuid4() for _ in range(events)]
    params = {"e": ready.endpoint_id, "refusal": None, "read": 0, "ids": ids,
              "sealed": [sealed(ready, i, {"type": "ap_down", "site": "lyon"}) for i in ids],
              "versions": [1] * events, "dedupe": [None] * events, "digests": [None] * events}  # fmt: skip
    async with owner_sessionmaker() as s, s.begin():  # ingress's own recording function, as its role would call it
        assert (await s.execute(RECORD, params)).scalar_one()["outcome"] == "recorded"

    rotation, busy, verified = dispatch.Rotation(), matching.Busy(), matching.Verified()
    runs = events * fan_out
    left = text("select count(*) from runs where tenant_id = :t and (status = 'running' or started_at is null)")
    made = text("select count(*) from runs where tenant_id = :t")
    cycles, dispatched, dispatching, most_queued = 0, Counter[str](), 0.0, 0
    queued = text("select count(*) from run_requests where tenant_id = :t and status = 'queued'")
    began = time.monotonic()
    async with serving(server.client, DbRunStore(worker_sessionmaker, FixtureKeys())):
        # A cycle's own work (its matching, its dispatch), then its sleep: `main.cycle` itself would read the current
        # build from Temporal, whose id the harness's build (not a release's) doesn't give, and do nothing
        while time.monotonic() - began < DEADLINE_S:
            async with owner_sessionmaker() as s, s.begin():  # the worker checks in, as a live one does (90 s window)
                await s.execute(text("update worker_instances set checked_at = statement_timestamp()"))
            dispatched.update(await matching.match_once(dispatch_sessionmaker, KEYS, verified, busy=busy))
            async with owner_sessionmaker() as s:
                most_queued = max(most_queued, (await s.execute(queued, {"t": ready.tenant_id})).scalar_one())
            passed = time.perf_counter()
            dispatched.update(
                await dispatch.dispatch_once(dispatch_sessionmaker, server.client, KEYS, api_settings, BUILD, rotation)
            )
            dispatching += time.perf_counter() - passed
            cycles += 1
            async with owner_sessionmaker() as s:
                done = (await s.execute(made, {"t": ready.tenant_id})).scalar_one() == runs
                if done and not (await s.execute(left, {"t": ready.tenant_id})).scalar_one():
                    break
            await asyncio.sleep(main.CYCLE_S)
    elapsed = time.monotonic() - began
    async with owner_sessionmaker() as s:
        rows = (await s.execute(text(
            "select extract(epoch from r.started_at - e.received_at), extract(epoch from r.ended_at - e.received_at), "
            "r.status from runs r join run_requests q on q.id = r.id join inbound_events e "
            "on q.idempotency_key like 'evt:' || e.id::text || ':%' where r.tenant_id = :t"),
            {"t": ready.tenant_id})).all()  # fmt: skip
        events_by = dict((await s.execute(text("select status, count(*) from inbound_events where tenant_id = :t "
                                               "group by status"), {"t": ready.tenant_id})).all())  # fmt: skip
        requests_by = {f"{st}:{why}": n for st, why, n in (await s.execute(text(
            "select status, coalesce(reason, ''), count(*) from run_requests where tenant_id = :t group by 1, 2"),
            {"t": ready.tenant_id})).all()}  # fmt: skip
        in_queue = [float(w) for (w,) in (await s.execute(text(
            "select extract(epoch from r.started_at - q.queued_at) from runs r join run_requests q on q.id = r.id "
            "where r.tenant_id = :t and r.started_at is not null"), {"t": ready.tenant_id})).all()]  # fmt: skip
    starts = [float(a) for a, _, _ in rows if a is not None]
    ends = [float(b) for _, b, _ in rows if b is not None]
    result = {
        "fan_out": fan_out, "events": events, "runs": runs, "runs_at_once": limit or 5, "started": len(starts),
        "ended": len(ends),
        "statuses": {status: sum(1 for *_, x in rows if x == status) for status in {x for *_, x in rows}},
        "events_by_status": events_by, "requests_by_status": requests_by,
        "cycles": cycles, "elapsed_s": round(elapsed, 1), "starts_per_s": round(len(starts) / elapsed, 2),
        "dispatched": dict(dispatched), "dispatch_s": round(dispatching, 1), "capacity": capacity,
        "most_queued": most_queued,
        "dispatch_ms_per_start": round(1000 * dispatching / max(1, dispatched["started"]), 1),
        "to_start_s": {"p50": round(_pct(starts, 0.5), 1), "p95": round(_pct(starts, 0.95), 1),
                       "max": round(max(starts), 1)} if starts else None,
        "to_end_s": {"p50": round(_pct(ends, 0.5), 1), "max": round(max(ends), 1)} if ends else None,
        "queued_to_start_s": {"p50": round(_pct(in_queue, 0.5), 1), "p95": round(_pct(in_queue, 0.95), 1),
                              "max": round(max(in_queue), 1)} if in_queue else None,
    }  # fmt: skip
    RESULTS.append(result)
    print(json.dumps(result))
    assert len(starts) == runs, result  # within the deadline: else the rates are far past what this path sustains
