# SPDX-License-Identifier: Apache-2.0
"""The engine blockers' reproductions at their real size, on Temporal's CLI dev server (the 2b-4b plan's M2: #16, #18,
#26): minutes each, too slow for the suite, where a fast regression pins each. And M2's measurement of a crossing that
grants 10,000 claims, end to end: the real `claims.grant` activity over Postgres (a test container). A run by hand,
never in CI (skipped unless `DEWPOINT_PROBE` is set); each prints what it measured. From `backend/`:

    DEWPOINT_PROBE=1 .venv/bin/pytest tests/probes/test_engine_issues.py -p no:randomly -s

These are this machine's numbers, on the dev server: evidence for the issues' acceptance, not supported figures."""

import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from temporalio import workflow
from temporalio.api.enums.v1 import EventType
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from dewpoint.apps.worker.activities import internal_activities
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.claims.service import NewClaim
from dewpoint.engine.handles import ClaimRef
from dewpoint.engine.runtime import bounds
from dewpoint.engine.runtime.activities import CLAIMS_GRANT, GrantInput
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.test_admission import KEYS
from tests.apps.worker.harness import MemoryStore, start
from tests.apps.worker.test_real_server import continued_inputs, issue_16, serving
from tests.core.retention.support import tenant
from tests.support.keys import FIXTURE_CONVERTER

pytestmark = pytest.mark.skipif(not os.environ.get("DEWPOINT_PROBE"), reason="a probe, run by hand (DEWPOINT_PROBE)")


@pytest.fixture(scope="module")
async def dev() -> AsyncIterator[WorkflowEnvironment]:
    """The dev server, as the suite's `dev_env` starts it."""
    drainage = ["matching.wv.VersionDrainageStatusVisibilityGracePeriod",
                "matching.wv.VersionDrainageStatusRefreshInterval"]  # fmt: skip
    args = [a for key in drainage for a in ("--dynamic-config-value", f'{key}="1s"')]
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER,
                                                     dev_server_extra_args=args) as environment:  # fmt: skip
        yield environment


async def test_issue_16s_reproduction_carries_on_within_the_snapshot_bound(dev: WorkflowEnvironment) -> None:
    """#16's acceptance at its real size: its reproduction (nested loops 10 x 10, each inner iteration 200 parallel
    steps) ends, every iteration done; no workflow task failed; each continued run's input within `SNAPSHOT_MAX`,
    encoded. Measured on `b5cbb9e`: succeeded in 240 s, 81 runs continued, the largest input 72,588 bytes."""
    client, store = dev.client, MemoryStore()
    loop = asyncio.get_running_loop()
    async with serving(client, store):
        handle = await start(client, store, issue_16(), checkpoint_events=300, drain_events=600, max_run_duration_s=900)
        t0 = loop.time()
        result = await asyncio.wait_for(handle.result(), 900)
        took = loop.time() - t0
    sizes, failures = await continued_inputs(client, handle)
    print(f"issue 16: {result.status} in {took:.1f} s; {len(sizes)} continued, largest {max(sizes, default=0)} bytes")
    assert (result.status, result.outputs) == ("succeeded", {"n": 10}), result
    assert failures == []
    assert sizes and max(sizes) <= bounds.SNAPSHOT_MAX


@workflow.defn(name="ProbeGrant", sandboxed=False)
class ProbeGrant:
    """One crossing, as the engine makes it (`Execution._crossing`): `claims.grant`, a minute an attempt."""

    @workflow.run
    async def run(self, data: GrantInput) -> None:
        await workflow.execute_activity(CLAIMS_GRANT, data, start_to_close_timeout=timedelta(minutes=1),
                                        retry_policy=RetryPolicy(maximum_attempts=1))  # fmt: skip


@pytest.mark.parametrize("claims", [1_000, 5_000, 10_000])
async def test_a_crossing_that_grants_many_claims(
    dev: WorkflowEnvironment, owner_sessionmaker, worker_sessionmaker, claims: int
) -> None:  # fmt: skip
    """The plan's M2 measurement: a run passes `claims` handles it holds to its child in one crossing (a sub-flow's
    input, a batch's items). #48 batched the grant's inserts; each claim is still fetched (its closure) and checked one
    at a time, in the real activity, against its one-minute timeout. As a real crossing's are (the review of the M2
    checkpoint, M3): output claims (two tables looked in), a tenth of them nesting a claim the value doesn't list (the
    closure fetches it), all held by grant, not owned (the grant looked up each time). Printed: the crossing end to end,
    and the activity alone. Measured on `e5769c5`: 1,100 claims 9.1 s, 5,500 39.8 s, 11,000 timed out at 60 s (about
    7 to 8 ms a claim): a crossing of 10,000 such claims fails. Flat input claims owned by the granter took 1.9 ms."""
    ctx = await tenant(owner_sessionmaker)
    t, owner, run, child = str(ctx["t"]), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    store = DbRunStore(worker_sessionmaker, KEYS)
    nested = [uuid.uuid4() for _ in range(claims // 10)]
    listed = [uuid.uuid4() for _ in range(claims)]
    made = [NewClaim(c, {"v": n}, (), owner, owner) for n, c in enumerate(nested)]
    made += [NewClaim(c, {"v": n, "inner": ClaimRef(str(nested[n // 10])).to_json()} if n % 10 == 0 else {"v": n}, (),
                      owner, owner) for n, c in enumerate(listed)]  # fmt: skip
    for at in range(0, len(made), 1_000):
        await store.write(t, made[at : at + 1_000], kind="output", step_id=None, iteration_key=None)
    every = [str(c.id) for c in made]
    await store.grant(t, granted_by=str(owner), to=str(run), claim_ids=every, root_run_id=str(owner))  # held by grant
    value = {"xs": [ClaimRef(str(c)).to_json() for c in listed]}
    queue = f"probe-grant-{uuid.uuid4()}"
    activities = internal_activities(store)
    async with Worker(dev.client, task_queue=queue, workflows=[ProbeGrant], activities=activities,
                      workflow_runner=UnsandboxedWorkflowRunner()):  # fmt: skip
        t0 = time.monotonic()
        handle = await dev.client.start_workflow(ProbeGrant.run, GrantInput(str(child), value, str(owner)),
                                                 id=run_workflow_id(t, str(run)), task_queue=queue)  # fmt: skip
        try:
            await handle.result()
            outcome = "granted"
        except Exception as e:  # noqa: BLE001  # a timeout is the measurement too
            outcome = type(e.cause if hasattr(e, "cause") and e.cause else e).__name__
        took = time.monotonic() - t0
    started = completed = None
    async for e in handle.fetch_history_events():
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED:
            started = e.event_time.ToDatetime()
        elif e.event_type in (EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED, EventType.EVENT_TYPE_ACTIVITY_TASK_FAILED,
                              EventType.EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT):  # fmt: skip
            completed = e.event_time.ToDatetime()
    activity_s = (completed - started).total_seconds() if started and completed else None
    print(f"grant {claims} (+{len(nested)} nested): {outcome}; crossing {took:.1f} s, activity {activity_s} s")
    assert outcome == "granted"
