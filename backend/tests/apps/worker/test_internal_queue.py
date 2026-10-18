# SPDX-License-Identifier: Apache-2.0
"""The engine's own activities (the projection, a batch's close, the claims crossings) have a queue of their own
(`INTERNAL_QUEUE`, the owner's ruling of 2026-10-18). A run's steps hold the engine queue's activity slots, never the
internal queue's, so every run's rows and ends land while all of those slots are held. Before the ruling, the run with
nothing but a 1-s delay, beside one run's 100 running steps, took 40 s on the dev server; a cancelled run of 100 steps
that never heartbeat ended only when they did, 42 s later.

Here the engine worker has one slot, which one step holds until the test lets it go: the production worker's 100 are
held the same way, by one run's `IN_FLIGHT_CAP` steps."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from temporalio import activity
from temporalio.api.enums.v1 import PendingActivityState
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.apps.worker.activities import engine_activities
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, StepInput, StepResult, step_activity
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, internal, run_id_of, start
from tests.support.graphs import G

HELD = "testkit.slow_echo@1"  # its activity here waits for the test to let it go, and never heartbeats


def graph() -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}}
    return g


@asynccontextmanager
async def one_slot(
    env: WorkflowEnvironment, store: MemoryStore, release: asyncio.Event
) -> AsyncIterator[asyncio.Event]:
    """The engine worker with one activity slot, and the internal worker: yields an event set once the held step's
    attempt has begun, holding the slot until `release`."""
    began = asyncio.Event()

    @activity.defn(name=step_activity(HELD))
    async def held(_: StepInput) -> StepResult:
        began.set()
        await release.wait()
        return StepResult({"value": None})

    engine = Worker(env.client, task_queue=ENGINE_QUEUE, workflows=[RunGraph, LoopBatch],
                    activities=[*engine_activities(store, []), held], max_concurrent_activities=1)  # fmt: skip
    async with engine, internal(env.client, store):
        yield began


async def test_another_run_ends_while_a_step_holds_every_engine_slot(env: WorkflowEnvironment) -> None:
    """A run with no plugin step writes its rows and its end through the internal queue alone: it ends while another
    run's step holds the engine queue's only slot."""
    store, release = MemoryStore(), asyncio.Event()
    async with one_slot(env, store, release) as began:
        holding = await start(env.client, store, graph().node("s", HELD, {"seconds": 0}), {})
        await asyncio.wait_for(began.wait(), RESULT_TIMEOUT_S)
        other = await start(env.client, store, graph().node("t", "flow.transform@1", {"fields": {"r": 1}}), {})
        result = await asyncio.wait_for(other.result(), RESULT_TIMEOUT_S)
        still = [(p.activity_type.name, p.state) for p in (await holding.describe()).raw_description.pending_activities]
        release.set()
        assert (await asyncio.wait_for(holding.result(), RESULT_TIMEOUT_S)).status == "succeeded"
    assert (result.status, store.runs[run_id_of(other)].status) == ("succeeded", "succeeded")
    assert still == [(step_activity(HELD), PendingActivityState.PENDING_ACTIVITY_STATE_STARTED)]  # its slot held


async def test_a_cancelled_run_ends_while_its_step_still_holds_its_slot(own_env: WorkflowEnvironment) -> None:
    """A cancel reaches a step that never heartbeats only when its attempt ends, and until then it holds its slot: the
    run's end lands at once all the same. On a test server of its own: the run closes with that attempt running, and a
    shared server would stop skipping time."""
    store, release = MemoryStore(), asyncio.Event()
    async with one_slot(own_env, store, release) as began:
        handle = await start(own_env.client, store, graph().node("s", HELD, {"seconds": 0}), {})
        await asyncio.wait_for(began.wait(), RESULT_TIMEOUT_S)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):  # before the step's attempt ends: only the test ends it
            await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
        release.set()
    assert store.runs[run_id_of(handle)].status == "cancelled"
    assert [(r.node_key, r.status) for r in store.steps(run_id_of(handle))] == [("s", "cancelled")]
