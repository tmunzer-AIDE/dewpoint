# SPDX-License-Identifier: Apache-2.0
"""The engine's Worker Deployment (spec §7), on Temporal's dev server: the test server refuses Worker Versioning.
A run is pinned to the build it started on, with its children and its continued runs, while new runs start on the
deployment's current build."""

import asyncio
import contextlib
import uuid
from dataclasses import dataclass

import pytest
from temporalio.api.enums.v1 import EventType, VersioningBehavior
from temporalio.client import Client, WorkflowHandle, WorkflowHistory
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.apps.worker import main
from dewpoint.apps.worker.activities import cel_activity
from dewpoint.apps.worker.deployment import deployment_config, describe, set_current, this_build
from dewpoint.apps.worker.main import engine_worker
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, cel_queue
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.worker.autocomplete_workflow import CancelsAnUnstartedActivity, echoed
from tests.apps.worker.harness import TENANT, MemoryStore, in_process, start
from tests.apps.worker.test_main import proven, settings, unrecorded
from tests.engine.replay.record import executions
from tests.support.graphs import G, cel, ref
from tests.support.plugins.testkit import TESTKIT


def build(name: str) -> str:
    """A build id of this test's own: each test's builds are new versions of the one deployment."""
    return f"{name}-{uuid.uuid4().hex[:8]}"


def engine(client: Client, store: MemoryStore, build_id: str) -> Worker:
    return engine_worker(client, store, [TESTKIT], settings(), build=build_id, identity=build_id)


@dataclass(frozen=True)
class Placement:
    """Where an execution's tasks ran. An activity's events don't name a version: its worker's identity does."""

    builds: set[str]  # the builds that completed its workflow tasks
    behaviours: set[int]  # the versioning behaviour each workflow task reported
    engine: set[str]  # the workers that ran its `dewpoint-engine` activities
    cel: set[tuple[str, str]]  # (task queue, worker) of its `cel.evaluate` activities


def placement(history: WorkflowHistory) -> Placement:
    queues = {
        e.event_id: e.activity_task_scheduled_event_attributes.task_queue.name
        for e in history.events
        if e.HasField("activity_task_scheduled_event_attributes")
    }
    started = [
        (queues[a.scheduled_event_id], a.identity)
        for e in history.events
        if e.HasField("activity_task_started_event_attributes")
        for a in [e.activity_task_started_event_attributes]
    ]
    tasks = [
        e.workflow_task_completed_event_attributes
        for e in history.events
        if e.HasField("workflow_task_completed_event_attributes")
    ]
    return Placement(
        builds={t.deployment_version.build_id for t in tasks},
        behaviours={t.versioning_behavior for t in tasks},
        engine={who for queue, who in started if queue == ENGINE_QUEUE},
        cel={(queue, who) for queue, who in started if queue != ENGINE_QUEUE},
    )


async def test_set_current_waits_for_the_builds_workers(dev_env: WorkflowEnvironment) -> None:
    """A version exists once one of its workers has polled: `set_current` retries until then, and gives up after its
    wait. `describe` then names the build new runs start on."""
    client, first = dev_env.client, build("first")
    with pytest.raises(RPCError):
        await set_current(client, build("nobody"), wait_s=1)
    promote = asyncio.create_task(set_current(client, first, wait_s=30))
    await asyncio.sleep(1)
    assert not promote.done()  # no worker of that build yet
    async with engine(client, MemoryStore(), first):
        await asyncio.wait_for(promote, 30)
        deployment = await describe(client)
    assert deployment.current == first and ("current" in {v.status for v in deployment.versions if v.build_id == first})


async def current_build(client: Client) -> str | None:
    """The build new runs start on; None until the deployment exists, which is once one of its workers has polled (a
    test that runs first in its process asks before then)."""
    try:
        return (await describe(client)).current
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return None
        raise


def graph() -> tuple[MemoryStore, G]:
    """A plugin step long enough to switch builds under it, then a sub-flow and a batched loop: children."""
    store = MemoryStore()
    sub = G()
    sub.settings = {
        "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
        "outputs": {"double": ref("steps.t.output.double")},
    }
    sub.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.n * 2")}})
    g = G()
    g.settings = {
        "input_schema": {"type": "object"},
        "outputs": {"double": ref("steps.r.output.double"), "count": ref("steps.l.output.count")},
    }
    g.node("s", "testkit.slow@1", {"seconds": 3}).node(
        "r", "flow.run_workflow@1", {"workflow_id": str(store.publish(sub)), "input": {"n": 21}}
    )
    g.node("l", "flow.loop@1", {"items": list(range(101))}).node("x", "testkit.echo@1", {"value": ref("item")})
    g.edge("s", "r").edge("r", "l").edge("l", "x", "body")
    return store, g


async def test_a_run_stays_on_the_build_it_started_on_with_its_children_and_continued_runs(
    dev_env: WorkflowEnvironment,
) -> None:
    client, old, new = dev_env.client, build("old"), build("new")
    store, g = graph()
    cel_worker = Worker(client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process, store)])
    async with engine(client, store, old), engine(client, store, new), cel_worker:
        await set_current(client, old)
        first = await start(client, store, g, {}, checkpoint_events=60)
        await asyncio.sleep(1)  # the plugin step is running on the old build
        await set_current(client, new)
        second = await start(client, store, g, {}, checkpoint_events=60)
        results = await asyncio.wait_for(asyncio.gather(first.result(), second.result()), 120)
        runs = [await executions(client, h.id, h.first_execution_run_id or "") for h in (first, second)]
    assert [(r.status, r.outputs) for r in results] == [("succeeded", {"double": 42, "count": 101})] * 2
    for handle, expected, chain in zip((first, second), (old, new), runs, strict=True):
        assert len(chain) >= 4, handle.id  # the run, a continued run, the sub-flow and the batch
        for history in chain:
            ran = placement(history)
            assert ran.builds == {expected} and ran.engine <= {expected}, (history.workflow_id, ran)
            assert ran.behaviours == {VersioningBehavior.VERSIONING_BEHAVIOR_PINNED}


async def completed_by_itself(handle: WorkflowHandle[object, str]) -> WorkflowHistory:
    """The history once a workflow task has completed after the cancelled activity's record."""
    for _ in range(100):
        history = await handle.fetch_history()
        types = [e.event_type for e in history.events]
        if EventType.EVENT_TYPE_ACTIVITY_TASK_CANCELED in types:
            after = types[types.index(EventType.EVENT_TYPE_ACTIVITY_TASK_CANCELED) :]
            if EventType.EVENT_TYPE_WORKFLOW_TASK_COMPLETED in after:
                return history
        await asyncio.sleep(0.2)
    raise AssertionError("no workflow task completed after the activity was cancelled")


async def test_a_run_stays_pinned_through_a_workflow_task_the_sdk_completes_by_itself(
    dev_env: WorkflowEnvironment,
) -> None:
    """A workflow task the SDK's core completes without the workflow reports the worker's default behaviour. Without
    one it reports none: Temporal takes the run as unversioned, and each start of its next activity on the run's own
    build begins a transition instead, with another such task, so the activity never starts and the run hangs (#22)."""
    client, version = dev_env.client, build("autocomplete")
    config = deployment_config(version)  # on the engine's queue: a later build is refused current without its queues
    async with Worker(
        client, task_queue=ENGINE_QUEUE, workflows=[CancelsAnUnstartedActivity], deployment_config=config
    ):
        await set_current(client, version)
        handle = await client.start_workflow(
            CancelsAnUnstartedActivity.run,
            f"nobody-{uuid.uuid4().hex[:8]}",
            id=run_workflow_id(TENANT, str(uuid.uuid4())),
            task_queue=ENGINE_QUEUE,
        )
        try:
            assert placement(await completed_by_itself(handle)).behaviours == {
                VersioningBehavior.VERSIONING_BEHAVIOR_PINNED
            }
            async with Worker(client, task_queue=ENGINE_QUEUE, activities=[echoed], deployment_config=config):
                assert await asyncio.wait_for(handle.result(), 20) == "ran"
        finally:
            with contextlib.suppress(RPCError):
                await handle.terminate()  # a run that hung isn't left running on the shared server


async def recorded(*args: object) -> None:
    """A deployment whose record matches the worker's namespace (engine 2b spec §2.1)."""


async def test_a_worker_set_to_makes_its_build_current_once_it_polls(
    dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compose runs one build at a time: its worker (DEWPOINT_WORKER_SET_CURRENT) promotes its own build, so new runs
    start on it. Here the database and the plugins are stand-ins: no run starts."""

    class Engine:
        async def dispose(self) -> None: ...

    async def connect(*args: object, **kwargs: object) -> Client:
        return dev_env.client

    monkeypatch.setattr(main.Client, "connect", connect)
    monkeypatch.setattr(main, "make_engine", lambda url: Engine())
    monkeypatch.setattr(main, "make_sessionmaker", lambda engine: None)
    monkeypatch.setattr(main, "verify_environment", recorded)  # the check itself: tests/apps/test_environment.py
    monkeypatch.setattr(main, "reporter", lambda *args: unrecorded)  # the record itself: tests/core/platform
    monkeypatch.setattr(main, "self_check", proven)  # the check itself: test_health.py
    monkeypatch.setattr(main, "installed_plugins", lambda: [TESTKIT])
    worker = asyncio.create_task(main.run(settings(worker_set_current=True, worker_shutdown_grace_s=0.1)))
    try:
        for _ in range(60):
            if await current_build(dev_env.client) == this_build():
                break
            await asyncio.sleep(0.5)
        assert await current_build(dev_env.client) == this_build()
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
