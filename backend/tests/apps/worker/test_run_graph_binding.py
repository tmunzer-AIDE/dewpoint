# SPDX-License-Identifier: Apache-2.0
"""#18: binding many CEL views in one workflow task stays within the SDK's deadlock timeout, however large the values
they share. Measuring a view's bindings for routing costs what it reads of them, never more than the local caps: a
value past them is known to be past them without being serialized. On the time-skipping server, the default build
(local CEL on); `tests/probes/test_engine_issues.py` runs it at the real size on the dev server."""

import asyncio
from typing import Any

from temporalio.testing import WorkflowEnvironment

from tests.apps.worker.harness import MemoryStore, start, workers
from tests.apps.worker.test_real_server import task_failures
from tests.support.graphs import G, cel, ref

SCHEMA: dict[str, Any] = {"type": "object", "properties": {"s": {"type": "string"}}, "required": ["s"]}


def issue_18(items: int) -> G:
    """#18's reproduction: a filter whose every item binds the same large string."""
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": {"code": ref("steps.f.error.code", default="none")}}
    g.node("f", "flow.filter@1", {"items": list(range(items)), "predicate": cel("size(trigger.s) > item")},
           on_error="continue")  # fmt: skip
    return g


async def test_issue_18s_thousand_views_of_a_large_string_end_with_a_step_result(env: WorkflowEnvironment) -> None:
    """#18's reproduction: 1,000 items each binding a 1.8 MiB string. Each view's measure serialized the string in
    full (about 1.8 GB of JSON in one workflow task), past the SDK's 2-second deadlock timeout: the task failed and
    retried, and the run had no result. It ends with the step's result (the binding set alone passes the request
    limit: `input_too_large`), no workflow task failed."""
    store = MemoryStore()
    async with workers(env.client, store):
        handle = await start(env.client, store, issue_18(1_000), {"s": "x" * (1_800 * 1024)})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"code": "input_too_large"}), result
    assert await task_failures(handle) == []
