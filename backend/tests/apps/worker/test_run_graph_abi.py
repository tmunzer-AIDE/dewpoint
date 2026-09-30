# SPDX-License-Identifier: Apache-2.0
"""A version runs only on a build of its engine ABI (spec §7). Admission refuses to start one of another ABI than the
current build's (tests/apps/test_runs.py, test_admission_abi.py), and publishing refuses to pin one
(tests/apps/test_workflow_ops.py). The version loader is the backstop, for a promotion that races a start: a run, a
sub-flow or a failure handler whose version was published for another ABI fails `version_unusable` before any of its
steps runs, saying to publish the workflow again."""

import asyncio
from typing import Any

from temporalio.testing import WorkflowEnvironment

from dewpoint.engine import ENGINE_ABI
from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, run_id_of, start, start_version, workers
from tests.support.graphs import G

OLD = ENGINE_ABI - 1  # the build before this one
ECHO, RUN = "testkit.echo@1", "flow.run_workflow@1"
REFUSED = (
    f"This version was published for engine ABI {OLD}, and this build runs ABI {ENGINE_ABI}: publish the workflow "
    f"again with a build of ABI {ENGINE_ABI}."
)


def echo() -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": {}}
    return g.node("a", ECHO, {"value": 1})


async def test_a_version_of_another_abi_fails_before_any_step_runs(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    version = store.add(echo(), engine_abi=OLD)
    async with workers(env.client, store):
        handle = await start_version(env.client, version)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.error is not None
    assert (result.status, result.error["code"], result.error["message"]) == ("failed", "version_unusable", REFUSED)
    assert store.steps(run_id_of(handle)) == []


async def test_a_sub_flow_or_failure_handler_of_another_abi_fails_where_it_starts(env: WorkflowEnvironment) -> None:
    """A parent of this build's ABI that still pins them: each fails as it loads, and the run's end, decided before
    its failure handler ran, stands."""
    store = MemoryStore()
    sub, handler = store.publish(echo(), engine_abi=OLD), store.publish(echo(), engine_abi=OLD)
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": {}, "failure_handler": str(handler)}
    g.node("r", RUN, {"workflow_id": str(sub), "input": {}})
    async with workers(env.client, store):
        handle = await start(env.client, store, g)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert (result.status, result.error["code"] if result.error else None) == ("failed", "version_unusable")
    ended: dict[str, Any] = {
        row.kind: (store.runs[child].status, store.runs[child].error_code, store.runs[child].error_message)
        for child, row in store.starts.items()
    }
    assert ended == {
        "subflow": ("failed", "version_unusable", REFUSED),
        "failure_handler": ("failed", "version_unusable", REFUSED),
    }
