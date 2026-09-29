# SPDX-License-Identifier: Apache-2.0
"""Continue-as-new (spec §6, 2a-3b): only at a quiescent point, opportunistically past `checkpoint_events`, or after
draining past `drain_events`. Nothing outstanding is cancelled, abandoned or restarted; a timer keeps its wake time;
the budget carries over; and draining adds a bounded number of events (the measured headroom test)."""

import asyncio
import dataclasses
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowFailureError, WorkflowHistory
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.runtime.activities import (
    BATCH,
    BUDGET,
    ENGINE_QUEUE,
    BatchInput,
    Parent,
    ProjectInput,
    VersionData,
)
from dewpoint.engine.runtime.workflow import LoopBatch
from tests.apps.worker.harness import TENANT, MemoryStore, start, workers
from tests.support.graphs import G, cel, ref
from tests.support.plugins.testkit import Slow, SlowSend

ECHO, LOOP, RUN = "testkit.echo@1", "flow.loop@1", "flow.run_workflow@1"
HEADROOM_EVENTS = 1_000  # spec §6: draining adds at most about this many events
HEADROOM_BYTES = 512 * 1024  # and this many bytes of history
DRAIN_AT = 100  # just past the first turn's commands: every unit has started, and none has ended


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": outputs}
    return g


async def chain(client: Client, workflow_id: str, first_run: str) -> list[WorkflowHistory]:
    """Every run of a continue-as-new chain, oldest first."""
    out: list[WorkflowHistory] = []
    run = first_run
    while run:
        history = await client.get_workflow_handle(workflow_id, run_id=run).fetch_history()
        out.append(history)
        last = history.events[-1]
        attrs = last.workflow_execution_continued_as_new_event_attributes
        run = (
            attrs.new_execution_run_id if last.HasField("workflow_execution_continued_as_new_event_attributes") else ""
        )
    return out


def snapshot(history: WorkflowHistory) -> dict[str, Any]:
    """The snapshot a run continued with: the continued run's input."""
    attrs = history.events[-1].workflow_execution_continued_as_new_event_attributes
    return dict(json.loads(attrs.input.payloads[0].data)["snapshot"])


def count(histories: list[WorkflowHistory], kind: int) -> int:
    return sum(e.event_type == kind for h in histories for e in h.events)


async def test_a_long_run_continues_as_new_and_ends_as_it_would_have(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(items=ref("steps.l.output.items"))
    g.node("l", LOOP, {"items": list(range(40)), "collect": ref("steps.x.output.value")})
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, checkpoint_events=120)
        result = await asyncio.wait_for(handle.result(), 60)
        runs = await chain(env.client, handle.id, handle.first_execution_run_id or "")
    assert len(runs) >= 2, "it never continued as new"
    assert (result.status, result.outputs) == ("succeeded", {"items": list(range(40))})
    assert result.iterations == 40  # the budget carried over: no fresh cap after continue-as-new
    continued = json.loads(
        runs[0].events[-1].workflow_execution_continued_as_new_event_attributes.input.payloads[0].data
    )
    assert continued["iterations"] == continued["snapshot"]["scheduler"]["budget"]["used"] > 0  # outside it too (M6)
    rows = [r for r in store.steps(handle.id) if r.node_key == "x"]
    assert len(rows) == 40 and {(r.attempt, r.status) for r in rows} == {(1, "succeeded")}


@dataclasses.dataclass
class SlowFlush(MemoryStore):
    """The rows the run writes just before it continues as new take a while to land: `a`'s last row goes then."""

    flushing: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    async def project(self, data: ProjectInput) -> None:
        if any(r.node_key == "a" and r.status == "succeeded" for r in data.steps):
            self.flushing.set()
            await asyncio.sleep(1)
        await super().project(data)


async def test_a_cancel_while_the_run_gets_ready_to_continue_as_new_ends_it_cancelled(env: WorkflowEnvironment) -> None:
    """A continued run wouldn't inherit the cancel, and would carry on: the run ends cancelled instead."""
    store = SlowFlush()
    g = graph().node("a", ECHO, {"value": 1}).node("b", ECHO, {"value": 2}).edge("a", "b")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, checkpoint_events=10)  # past it once `a` has run
        await asyncio.wait_for(store.flushing.wait(), 30)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 30)
        runs = await chain(env.client, handle.id, handle.first_execution_run_id or "")
    assert len(runs) == 1 and store.runs[handle.id].status == "cancelled"
    assert [(r.node_key, r.status) for r in store.steps(handle.id)] == [("a", "succeeded")]  # `b` never started


@dataclasses.dataclass
class SlowRunning(MemoryStore):
    """The projection of `a`'s `running` row takes 3 s. `c` ending next to `a` sends it (a queued row alone doesn't
    wake the run); `a` (1 s) ends meanwhile, and the run reaches its quiescent point with it still in flight."""

    projecting: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    async def project(self, data: ProjectInput) -> None:
        if any(r.node_key == "a" and r.status == "running" for r in data.steps):
            self.projecting.set()
            await asyncio.sleep(3)
        await super().project(data)


async def test_a_cancel_while_the_run_settles_for_continue_as_new_lets_its_projection_land(
    env: WorkflowEnvironment,
) -> None:
    """2a-3b's final review, M8: the run waits for the projection in flight before continuing. A cancel then used to
    cancel that projection too; it lands, and the run ends cancelled."""
    store = SlowRunning()
    g = graph().node("a", "testkit.slow@1", {"seconds": 1}).node("c", ECHO, {"value": 1})
    g.node("b", ECHO, {"value": 2}).edge("a", "b").edge("c", "b")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, checkpoint_events=10)
        await asyncio.wait_for(store.projecting.wait(), 30)
        first = env.client.get_workflow_handle(handle.id, run_id=handle.first_execution_run_id)
        for _ in range(100):  # until `a` has ended: the run now waits for the projection to continue
            history = await first.fetch_history()
            slow = {
                e.event_id
                for e in history.events
                if e.HasField("activity_task_scheduled_event_attributes")
                and e.activity_task_scheduled_event_attributes.activity_type.name.startswith("testkit.slow")
            }
            if any(
                e.activity_task_completed_event_attributes.scheduled_event_id in slow
                for e in history.events
                if e.HasField("activity_task_completed_event_attributes")
            ):
                break
            await asyncio.sleep(0.05)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 30)
        history = await first.fetch_history()
    requested = [e for e in history.events if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_CANCEL_REQUESTED]
    assert requested == [] and store.runs[handle.id].status == "cancelled"
    assert sorted(r.node_key for r in store.steps(handle.id)) == ["a", "c"]  # `b` never started


def doubler() -> G:
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
        "outputs": {"double": ref("steps.t.output.double")},
    }
    g.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.n * 2")}})
    return g


async def test_draining_settles_what_is_outstanding_and_a_timer_keeps_its_wake_time(
    own_env: WorkflowEnvironment,
) -> None:
    """Spec §6's threshold test: drain mode is entered while loop-batch children, a sub-flow, activities and a timer
    are outstanding. No child is terminated or restarted, each activity completes once, the timer fires at its
    original wake time, and the continued run carries on from the snapshot."""
    store = MemoryStore()
    sub = store.publish(doubler())
    g = graph(double=ref("steps.r.output.double"), count=ref("steps.l.output.count"))
    g.node("s", LOOP, {"items": [1, 2, 3, 4, 5], "concurrency": 5})
    g.node("send", "testkit.slow_send@1", {"seconds": 2}).edge("s", "send", "body")
    g.node("d", "flow.delay@1", {"duration_s": 3600})
    g.node("l", LOOP, {"items": list(range(150))}).node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    g.node("r", RUN, {"workflow_id": str(sub), "input": {"n": 21}})
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {}, drain_events=15)
        result = await asyncio.wait_for(handle.result(), 120)
        runs = await chain(own_env.client, handle.id, handle.first_execution_run_id or "")
    assert (result.status, result.outputs) == ("succeeded", {"double": 42, "count": 150})
    assert len(runs) >= 2, "it never drained"
    assert SlowSend.sent.count(handle.id) == 5  # each ambiguous send once
    started = count(runs, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED)
    assert started == 3  # two batches and the sub-flow, none restarted
    assert count(runs, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_TERMINATED) == 0
    carried = [s for s in (snapshot(h) for h in runs[:-1]) if s["timers"]]
    assert carried, "the timer never went into a snapshot"
    [delay] = [r for r in store.steps(handle.id) if r.node_key == "d"]
    assert delay.started_at and delay.ended_at
    took = datetime.fromisoformat(delay.ended_at) - datetime.fromisoformat(delay.started_at)
    assert timedelta(seconds=3599) <= took <= timedelta(seconds=3601), took  # its original wake time


async def test_the_headroom_draining_adds_is_measured_and_bounded(own_env: WorkflowEnvironment) -> None:
    """Spec §10's measured headroom test. Draining begins with the in-flight cap saturated: 80 slow activities that
    heartbeat, 10 activities that fail once and retry, and 10 sub-flows that ask for more budget once they're past a
    slow step. The retries, the heartbeats and the grants all happen while it drains. What draining added, in events
    and bytes, is recorded in the snapshot, and stays within the headroom."""
    store = MemoryStore()
    sub = G()
    sub.settings = {
        "input_schema": {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]},
        "outputs": {"n": ref("steps.k.output.count")},
    }
    sub.node("s", "testkit.slow@1", {"seconds": 1})  # so it asks for budget while its parent drains
    sub.node("k", "flow.filter@1", {"items": ref("trigger.items"), "predicate": cel("true")}).edge("s", "k")
    sub_id = store.publish(sub)
    g = graph()
    for i in range(8):  # 80 slow activities, heartbeating each second
        g.node(f"l{i}", LOOP, {"items": list(range(10)), "concurrency": 10})
        g.node(f"w{i}", "testkit.slow@1", {"seconds": 3}).edge(f"l{i}", f"w{i}", "body")
    g.node("f", LOOP, {"items": list(range(10)), "concurrency": 10})  # 10 that fail once, then retry
    g.node("fail", "testkit.fail_n@1", {"failures": 1}).edge("f", "fail", "body")
    g.node("c", LOOP, {"items": [list(range(1_200))] * 10, "concurrency": 10})  # 10 sub-flows that ask for more
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": ref("item")}}).edge("c", "r", "body")
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {}, drain_events=DRAIN_AT)
        result = await asyncio.wait_for(handle.result(), 180)
        runs = await chain(own_env.client, handle.id, handle.first_execution_run_id or "")
    assert result.status == "succeeded", result.error
    assert len(runs) >= 2, "it never drained"
    drained = snapshot(runs[0])["drained"]
    assert drained["units"] == {"activities": 90, "children": 10}  # the cap was saturated when draining began
    (began, continued), (size_began, size_continued) = drained["events"], drained["bytes"]
    during = [e for e in runs[0].events if began < e.event_id <= continued]
    retried = [
        e
        for e in during
        if e.HasField("activity_task_scheduled_event_attributes")
        and e.activity_task_scheduled_event_attributes.activity_type.name == "testkit.fail_n.v1"
    ]
    granted = [
        e
        for e in during
        if e.HasField("signal_external_workflow_execution_initiated_event_attributes")
        and e.signal_external_workflow_execution_initiated_event_attributes.signal_name == BUDGET
    ]
    assert (len(retried), len(granted)) == (10, 10)  # every retry and every grant happened while draining
    beats = [at for run, at in Slow.beats if run == handle.id]
    assert len(beats) == 80 * 3 and min(beats) > datetime.fromisoformat(drained["at"])  # and every heartbeat
    events, added = continued - began, size_continued - size_began
    print(f"draining added {events} events and {added} bytes")  # the measurement the headroom is set from
    assert events <= HEADROOM_EVENTS and added <= HEADROOM_BYTES


async def test_a_snapshot_of_another_format_fails_the_run(env: WorkflowEnvironment) -> None:
    """Decision 16: a continued run whose snapshot this build can't read ends `internal_error`; it never hangs. It
    still reports the iterations it used before continuing, which its input carries outside the snapshot (2a-3b's
    final review, M6: it reported 0)."""
    store = MemoryStore()
    g = graph().node("a", ECHO, {"value": 1})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, snapshot={"snapshot_format": 99}, iterations=37)
        result = await asyncio.wait_for(handle.result(), 30)
    assert (result.status, result.error["code"], result.iterations) == ("failed", "internal_error", 37)
    assert store.runs[handle.id].iterations == 37


async def test_a_batch_with_a_snapshot_of_another_format_fails_as_a_workflow(env: WorkflowEnvironment) -> None:
    """Its parent then fails the loop (decision 4) instead of waiting for a batch that can't carry on."""
    store = MemoryStore()
    version = store.add(graph().node("l", LOOP, {"items": [1]}).node("x", ECHO).edge("l", "x", "body"))
    now = (await env.get_current_time()).isoformat()
    parent = Parent("nobody", str(uuid.uuid4()), str(uuid.uuid4()), "", BATCH, now, 0)
    batch = BatchInput(
        TENANT, parent.run_id, version, str(uuid.uuid4()), [], [], 0, 1, True, {}, {}, now, parent,
        snapshot={"snapshot_format": 99},
    )  # fmt: skip
    async with workers(env.client, store):
        handle = await env.client.start_workflow(LoopBatch.run, batch, id=str(uuid.uuid4()), task_queue=ENGINE_QUEUE)
        with pytest.raises(WorkflowFailureError) as failed:
            await asyncio.wait_for(handle.result(), 30)
    assert isinstance(failed.value.cause, ApplicationError) and failed.value.cause.type == "internal_error"


@dataclasses.dataclass
class LosesTheSubFlow(MemoryStore):
    """The sub-flow's version loads once: its continued run finds it gone, or unable to compile."""

    sub_version: str = ""
    lose: str = "load"
    loads: int = 0

    async def version(self, tenant_id: str, version_id: str) -> VersionData:
        data = await super().version(tenant_id, version_id)
        if version_id != self.sub_version:
            return data
        self.loads += 1
        if self.loads == 1:
            return data
        if self.lose == "load":
            raise ApplicationError(f"version {version_id} not found", type="version_not_found", non_retryable=True)
        return dataclasses.replace(data, manifests={})  # this build can't compile it


@pytest.mark.parametrize("lose", ["load", "compile"])
async def test_a_continued_sub_flow_that_cant_load_its_version_reports_what_it_used(
    env: WorkflowEnvironment, lose: str
) -> None:
    """Checkpoint 3's review: a continued run that ended before restoring its snapshot (its version didn't load or
    compile, or a cancel came while it loaded) reported 0 iterations, so its parent released budget it had spent."""
    store = LosesTheSubFlow(lose=lose)
    sub = graph(items=ref("steps.l.output.items"))
    sub.node("l", LOOP, {"items": list(range(40)), "collect": ref("steps.x.output.value")})
    sub.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    sub_id = store.publish(sub)
    store.sub_version = str(store.subflows[sub_id].version_id)
    g = graph().node("r", RUN, {"workflow_id": str(sub_id), "input": {}})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, checkpoint_events=120)
        result = await asyncio.wait_for(handle.result(), 60)
        [child] = [run_id for run_id, row in store.starts.items() if row.kind == "subflow"]
        started = (await env.client.get_workflow_handle(child).fetch_history()).events[0]
    carried = json.loads(started.workflow_execution_started_event_attributes.input.payloads[0].data)["iterations"]
    assert store.loads == 2 and carried > 0  # it continued as new, then couldn't run its version
    assert (store.runs[child].error_code, store.runs[child].iterations) == ("version_unusable", carried)
    assert result.error is not None
    assert (result.status, result.error["code"], result.iterations) == ("failed", "version_unusable", carried)
