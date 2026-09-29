# SPDX-License-Identifier: Apache-2.0
"""The two-build deployment test (spec §7, §10), on Temporal's dev server. Build N-1 drains while build N serves new
runs, and N lacks a node type retired in between (`testkit.slow`). The N-1 run uses that type, and runs plugin
activities, a sub-flow, a loop batch, CEL and continue-as-new. Every engine task of it (workflow tasks and
`dewpoint-engine` activities, in the run, its children and its continued runs) runs on N-1. `cel.evaluate` is outside
the deployment, deliberately: each CEL task runs on a worker serving the version's profile. Once its runs have ended,
N-1 reports itself drained."""

import asyncio

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.apps.worker.activities import cel_activity
from dewpoint.apps.worker.deployment import describe, set_current
from dewpoint.apps.worker.main import engine_worker
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import cel_queue
from dewpoint.sdk import Plugin
from tests.apps.worker.harness import MemoryStore, in_process, start
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
    old.node("l", "flow.loop@1", {"items": list(range(101)), "collect": cel("item * 2")})
    old.node("x", "testkit.echo@1", {"value": ref("item")})
    old.edge("s", "r").edge("r", "l").edge("l", "x", "body")
    new = G()  # N's: nothing retired
    new.settings = {
        "input_schema": {"type": "object"},
        "outputs": {"n": cel("steps.e.output.value + 1")},
    }
    new.node("e", "testkit.echo@1", {"value": 41})
    return store, old, new


async def test_the_old_build_drains_while_the_new_one_serves_new_runs(dev_env: WorkflowEnvironment) -> None:
    client, n1, n = dev_env.client, build("n-1"), build("n")
    store, old_graph, new_graph = graphs()
    evaluator = Worker(
        client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process)], identity=CEL
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
    slow = [r for r in store.steps(old.id) if r.node_key == "s"]
    assert [(r.status, r.attempt) for r in slow] == [("succeeded", 1)]  # the retired type ran on N-1, once
    for chain, expected in ((chains[0], n1), (chains[1], n)):
        assert len(chain) >= (4 if expected == n1 else 1)
        cel_tasks = set()
        for history in chain:
            ran = placement(history)
            assert ran.builds == {expected} and ran.engine <= {expected}, (history.workflow_id, ran)
            cel_tasks |= ran.cel
        assert cel_tasks == {(cel_queue(CURRENT_CEL_PROFILE), CEL)}  # on the version's profile, and only there
