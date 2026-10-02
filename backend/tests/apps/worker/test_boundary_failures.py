# SPDX-License-Identifier: Apache-2.0
"""What the activity boundary does when the claim store fails around a plugin step (engine 2b spec §3.7, the review's
I5). Before the node runs, a store that doesn't answer fails the attempt retryable, never as an ambiguous outcome:
nothing was sent. After it ran, a failure stays the node's even when the index can't be read again to mask its
message. Claims nested past NESTING_MAX are refused as any unreadable claim is, `claim_unavailable`."""

import asyncio
import uuid
from typing import Any

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.worker import claims
from dewpoint.core.claims.secret_index import SECRET_INDEX_UNAVAILABLE, Index
from dewpoint.engine.handles import NESTING_MAX
from dewpoint.engine.runtime.activities import step_activity
from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, run_id_of, start, start_version, workers
from tests.support.graphs import G, ref


@pytest.fixture(autouse=True)
def fresh() -> None:
    claims.SECRETS.clear()


class Flaky(MemoryStore):
    """A store whose index reads fail `fail_reads` times, and whose version checks fail inside the activity named
    `fail_versions_in`: a database that stops answering just then."""

    def __init__(self, *, fail_reads: int = 0, fail_versions_in: str | None = None) -> None:
        super().__init__()
        self.fail_reads, self.fail_versions_in = fail_reads, fail_versions_in

    async def index(self, tenant_id: str, root_run_id: str) -> Index:
        if self.fail_reads > 0:
            self.fail_reads -= 1
            raise ConnectionError("the database didn't answer")
        return await super().index(tenant_id, root_run_id)

    async def index_version(self, tenant_id: str, root_run_id: str) -> int:
        if self.fail_versions_in is not None and activity.info().activity_type == self.fail_versions_in:
            raise ConnectionError("the database didn't answer")
        return await super().index_version(tenant_id, root_run_id)


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object", "additionalProperties": False}, "outputs": outputs}
    return g


async def test_a_store_that_doesnt_answer_before_an_ambiguous_node_runs_is_retried_never_unknown(
    env: WorkflowEnvironment,
) -> None:
    """The index can't be read before the attempt: nothing was sent, so the attempt fails retryable with
    `secret_index_unavailable` and no outcome, and the next one runs the node."""
    store = Flaky(fail_reads=1)
    g = graph().node("p", "testkit.ambiguous_send@1", {"outcome": "sent"})
    g.nodes[-1]["options"]["max_attempts"] = 3
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.status == "succeeded", result.error
    rows = sorted(store.steps(run_id_of(handle)), key=lambda r: r.attempt)
    assert [(r.attempt, r.error_code, r.outcome) for r in rows] == [
        (1, SECRET_INDEX_UNAVAILABLE, None),
        (2, None, "applied"),
    ]


async def test_a_failure_stays_the_nodes_when_the_index_cant_be_read_again(env: WorkflowEnvironment) -> None:
    """The node ran and failed for good; masking its message would read the index again, which fails: the message
    is masked with what the boundary already holds, and the failure stays the node's, never retried."""
    store = Flaky(fail_versions_in=step_activity("testkit.slow_echo@1"))
    g = graph(code=ref("steps.f.error.code", default=""))
    g.node("f", "testkit.slow_echo@1", {"seconds": 0, "value": 1, "fail": True}, on_error="continue")
    g.nodes[-1]["options"]["max_attempts"] = 3
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.outputs == {"code": "echo_failed"}
    assert [r.attempt for r in store.steps(run_id_of(handle)) if r.node_key == "f"] == [1]  # never run again


def nested(store: MemoryStore, run_id: str) -> Any:
    """A handle to claims nested past NESTING_MAX, each owned by `run_id`."""
    handle: Any = "deepest"
    for _ in range(NESTING_MAX + 2):
        handle = store.claim({"in": handle}, owner=run_id, tainted=False)
    return handle


def reading(outputs: dict[str, Any]) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object", "properties": {"v": {}}, "required": ["v"]}, "outputs": outputs}
    return g


async def test_claims_nested_past_the_bound_are_refused_as_unavailable(env: WorkflowEnvironment) -> None:
    store, run_id = MemoryStore(), str(uuid.uuid4())
    g = reading({"code": ref("steps.e.error.code", default="")})
    g.node("e", "testkit.echo@1", {"value": ref("trigger.v")}, on_error="continue")
    g.nodes[-1]["options"]["max_attempts"] = 1
    async with workers(env.client, store):
        wf = await start_version(env.client, store.add(g), {"v": nested(store, run_id)}, run_id=run_id)
        result = await asyncio.wait_for(wf.result(), RESULT_TIMEOUT_S)
    assert result.outputs == {"code": "claim_unavailable"}


async def test_a_reference_reading_claims_nested_past_the_bound_is_refused_as_unavailable(
    env: WorkflowEnvironment,
) -> None:
    """The claims activities read nested claims too: a reference with a default, read through them by
    `claims.derive`, fails the run as any unreadable claim does, never as an internal error."""
    store, run_id = MemoryStore(), str(uuid.uuid4())
    g = reading({"deep": ref("trigger.v" + ".in" * (NESTING_MAX + 2), default="")})
    async with workers(env.client, store):
        wf = await start_version(env.client, store.add(g), {"v": nested(store, run_id)}, run_id=run_id)
        result = await asyncio.wait_for(wf.result(), RESULT_TIMEOUT_S)
    assert result.status == "failed" and result.error is not None
    assert result.error["code"] == "claim_unavailable", result.error
