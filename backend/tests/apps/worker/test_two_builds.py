# SPDX-License-Identifier: Apache-2.0
"""The two-build deployment test (spec §7, §10), on Temporal's dev server. Build N-1 drains while build N serves new
runs, and N lacks a node type retired in between (`testkit.slow`). The N-1 run uses that type, and runs plugin
activities, a sub-flow, a loop batch, CEL and continue-as-new. Every engine task of it (workflow tasks and
`dewpoint-engine` activities, in the run, its children and its continued runs) runs on N-1. `cel.evaluate` is outside
the deployment, deliberately: each CEL task runs on a worker serving the version's profile. Once its runs have ended,
N-1 reports itself drained.

A new engine ABI adds a rule: a version runs only on a build of its ABI. After the promotion, a new run of a version
the old build published, or of one pinning such a sub-flow, fails until each workflow is published again."""

import asyncio
import dataclasses
from collections.abc import Sequence
from typing import Any

from temporalio.api.common.v1 import Payload
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowHandle
from temporalio.converter import DataConverter, PayloadCodec
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.apps.worker.activities import cel_activity
from dewpoint.apps.worker.deployment import describe, set_current
from dewpoint.apps.worker.main import engine_worker
from dewpoint.engine import ENGINE_ABI
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import CEL_EVALUATE, cel_queue
from dewpoint.sdk import Plugin
from tests.apps.worker.harness import EVALUATOR_ONLY, MemoryStore, in_process, run_id_of, start, start_version
from tests.apps.worker.test_deployment import build, placement
from tests.apps.worker.test_main import settings
from tests.engine.replay.record import executions
from tests.support.graphs import G, cel, ref
from tests.support.plugins.testkit import TESTKIT, Slow

WITHOUT_SLOW = Plugin(TESTKIT.name, TESTKIT.version, tuple(n for n in TESTKIT.nodes if n is not Slow))
CEL = f"cel:{CURRENT_CEL_PROFILE}"  # the evaluator worker's identity: the profile it serves


def graphs() -> tuple[MemoryStore, G, G]:
    store = MemoryStore()
    sub = G()
    sub.settings = {
        "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
        "outputs": {"double": ref("steps.t.output.double")},
    }
    sub.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.n * 2")}})
    old = G()  # N-1's run: the retired type, a sub-flow, a loop batch with CEL, and continue-as-new
    old.settings = {"input_schema": {"type": "object"}, "outputs": {"double": ref("steps.r.output.double")}}
    old.node("s", "testkit.slow@1", {"seconds": 3})
    old.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(sub)), "input": {"n": 21}})
    old.node("l", "flow.loop@1", {"items": list(range(101)), "collect": cel(f"item + {EVALUATOR_ONLY}")})
    old.node("x", "testkit.echo@1", {"value": ref("item")})
    old.edge("s", "r").edge("r", "l").edge("l", "x", "body")
    new = G()  # N's: nothing retired
    new.settings = {
        "input_schema": {"type": "object"},
        "outputs": {"n": cel(f"41 + {EVALUATOR_ONLY}")},  # in the evaluator, reading nothing sensitive
    }
    new.node("e", "testkit.echo@1", {"value": 41})
    return store, old, new


async def test_the_old_build_drains_while_the_new_one_serves_new_runs(dev_env: WorkflowEnvironment) -> None:
    client, n1, n = dev_env.client, build("n-1"), build("n")
    store, old_graph, new_graph = graphs()
    evaluator = Worker(
        client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process, store)], identity=CEL
    )
    async with evaluator, engine_worker(client, store, [TESTKIT], settings(), build=n1, identity=n1):
        await set_current(client, n1)
        old = await start(client, store, old_graph, {}, checkpoint_events=60)
        async with engine_worker(client, store, [WITHOUT_SLOW], settings(), build=n, identity=n):
            await asyncio.sleep(1)  # N-1's run is in its `testkit.slow` step
            await set_current(client, n)
            new = await start(client, store, new_graph, {})
            done = await asyncio.wait_for(asyncio.gather(old.result(), new.result()), 120)
            for _ in range(60):  # N-1 has no run left: Temporal reports it drained
                statuses = {v.build_id: v.status for v in (await describe(client)).versions}
                if statuses.get(n1) == "drained":
                    break
                await asyncio.sleep(0.5)
        chains = [await executions(client, h.id, h.first_execution_run_id or "") for h in (old, new)]
    assert [(r.status, r.outputs) for r in done] == [("succeeded", {"double": 42}), ("succeeded", {"n": 42})]
    assert (statuses[n1], statuses[n]) == ("drained", "current")
    slow = [r for r in store.steps(run_id_of(old)) if r.node_key == "s"]
    assert [(r.status, r.attempt) for r in slow] == [("succeeded", 1)]  # the retired type ran on N-1, once
    for chain, expected in ((chains[0], n1), (chains[1], n)):
        assert len(chain) >= (4 if expected == n1 else 1)
        cel_tasks = set()
        for history in chain:
            ran = placement(history)
            assert ran.builds == {expected} and ran.engine <= {expected}, (history.workflow_id, ran)
            cel_tasks |= ran.cel
        assert cel_tasks == {(cel_queue(CURRENT_CEL_PROFILE), CEL)}  # on the version's profile, and only there


LEGACY_CEL_QUEUE = f"dewpoint-cel.{CURRENT_CEL_PROFILE}"  # the CEL queue every build before ABI 5 polls


class PlainCodec(PayloadCodec):
    """A build before ABI 5 has no codec. This one counts each payload it's given; it can't read an encrypted one."""

    def __init__(self) -> None:
        self.decoded = 0

    async def encode(self, payloads: Sequence[Payload]) -> list[Payload]:
        return list(payloads)

    async def decode(self, payloads: Sequence[Payload]) -> list[Payload]:
        self.decoded += len(payloads)
        return list(payloads)


async def scheduled(handle: WorkflowHandle[Any, Any], activity_type: str) -> None:
    """Until the run has scheduled an activity of that type."""
    for _ in range(100):
        async for e in handle.fetch_history_events():
            attributes = e.activity_task_scheduled_event_attributes
            if (
                e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
                and attributes.activity_type.name == activity_type
            ):
                return
        await asyncio.sleep(0.1)
    raise AssertionError(f"{handle.id} never scheduled {activity_type}")


async def test_a_cel_worker_of_an_older_abi_never_receives_this_builds_requests(dev_env: WorkflowEnvironment) -> None:
    """Review finding (2b-1a): `cel.evaluate` queues are outside the deployment, and from ABI 5 on a request is
    encrypted, which a build before it can't read (nor can this build read that one's plain requests). Each ABI's
    requests go to a queue of its own, so an older build's CEL worker, still serving its draining runs, never gets
    this build's (2b spec §6.6). Here only the older queue is served until the request has waited; then this build's
    CEL worker serves it."""
    client, n = dev_env.client, build("cel-n")
    store, _, new_graph = graphs()
    older = PlainCodec()
    old_client = Client(
        client.service_client,
        namespace=client.namespace,
        data_converter=dataclasses.replace(DataConverter.default, payload_codec=older),
    )
    old_cel = Worker(old_client, task_queue=LEGACY_CEL_QUEUE, activities=[cel_activity(in_process)])
    async with old_cel, engine_worker(client, store, [TESTKIT], settings(), build=n, identity=n):
        await set_current(client, n)
        run = await start(client, store, new_graph, {})
        await scheduled(run, CEL_EVALUATE)
        await asyncio.sleep(2)  # the older build's CEL worker polls all along
        assert older.decoded == 0
        async with Worker(
            client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process, store)]
        ):
            result = await asyncio.wait_for(run.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"n": 42})


async def pinned(handle: WorkflowHandle[Any, Any]) -> None:
    """Until the run's first workflow task has completed: from then on, it's pinned to that task's build."""
    for _ in range(100):
        if any(e.HasField("workflow_task_completed_event_attributes") for e in (await handle.fetch_history()).events):
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"{handle.id}'s first workflow task never completed")


async def test_after_a_new_abi_is_promoted_old_versions_wait_to_be_published_again(
    dev_env: WorkflowEnvironment,
) -> None:
    """N-1 runs the ABI before N's. A run it started finishes there, its sub-flow included. Once N is current, a new
    run of a version N-1 published fails before any step runs; so does the sub-flow of a parent published again on
    its own. Published again, child first, the workflow runs on N."""
    client, n1, n = dev_env.client, build("abi-n-1"), build("abi-n")
    old = ENGINE_ABI - 1
    store = MemoryStore()
    child = G()
    child.settings = {"input_schema": {"type": "object"}, "outputs": {"v": ref("steps.a.output.value")}}
    child.node("a", "testkit.echo@1", {"value": 1})
    child_id = store.publish(child, engine_abi=old)

    def parent() -> G:
        g = G()
        g.settings = {"input_schema": {"type": "object"}, "outputs": {"v": ref("steps.r.output.v")}}
        g.node("s", "testkit.slow@1", {"seconds": 2})
        g.node("r", "flow.run_workflow@1", {"workflow_id": str(child_id), "input": {}})
        return g.edge("s", "r")

    old_parent = store.add(parent(), engine_abi=old)
    async with engine_worker(client, store, [TESTKIT], settings(), build=n1, identity=n1, abi=old):
        await set_current(client, n1)
        on_old = await start_version(client, old_parent)  # in its slow step when N takes over
        await pinned(on_old)
        async with engine_worker(client, store, [TESTKIT], settings(), build=n, identity=n):
            await set_current(client, n)
            refused = await start_version(client, old_parent)
            parent_only = await start_version(client, store.add(parent()))  # it still pins N-1's child
            store.publish(child, child_id)
            both = await start_version(client, store.add(parent()))
            handles = (on_old, refused, parent_only, both)
            done = await asyncio.wait_for(asyncio.gather(*(h.result() for h in handles)), 120)
        chain = await executions(client, on_old.id, on_old.first_execution_run_id or "")
    refusal = f"This version was published for engine ABI {old}, and this build runs ABI {ENGINE_ABI}: publish the "
    refusal += f"workflow again with a build of ABI {ENGINE_ABI}."
    ended = [(r.status, (r.error or {}).get("code"), r.outputs) for r in done]
    assert ended == [
        ("succeeded", None, {"v": 1}),
        ("failed", "version_unusable", None),
        ("failed", "version_unusable", None),
        ("succeeded", None, {"v": 1}),
    ]
    assert (done[1].error or {}).get("message") == refusal
    [sub_run] = [c for c, row in store.starts.items() if row.parent_run_id == run_id_of(parent_only)]
    assert (store.runs[sub_run].error_code, store.runs[sub_run].error_message) == ("version_unusable", refusal)
    assert len(chain) == 2 and all(placement(h).builds == {n1} for h in chain)  # the run and its sub-flow, on N-1
