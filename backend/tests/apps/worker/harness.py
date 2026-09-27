# SPDX-License-Identifier: Apache-2.0
"""Run test graphs through `RunGraph` on Temporal's time-skipping test server, with the real step activities, an
in-memory store and an in-process CEL evaluator (the real one needs Linux and its own container)."""

import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from temporalio.client import Client, WorkflowHandle
from temporalio.worker import Worker, WorkflowRunner
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from dewpoint.apps.worker.activities import Evaluate, RunStore, cel_activity, engine_activities
from dewpoint.engine.cel import ipc
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.validate import SubflowInfo
from dewpoint.engine.runtime.activities import (
    ENGINE_QUEUE,
    LIVE,
    ProjectInput,
    RunInput,
    RunResult,
    RunSummary,
    StepRow,
    VersionData,
    cel_queue,
)
from dewpoint.engine.runtime.workflow import RunGraph
from dewpoint.sdk import Plugin
from tests.engine.runtime.support import MANIFESTS, expressions
from tests.support.graphs import G
from tests.support.plugins.testkit import TESTKIT

TENANT = str(uuid.UUID(int=1))


@dataclass
class MemoryStore:
    versions: dict[str, VersionData] = field(default_factory=dict)
    rows: dict[tuple[str, str, str, int], StepRow] = field(default_factory=dict)
    runs: dict[str, RunSummary] = field(default_factory=dict)
    subflows: dict[uuid.UUID, SubflowInfo] = field(default_factory=dict)  # what validation sees as published

    def add(self, g: G) -> str:
        version_id = str(uuid.uuid4())
        refs = {n["type"] for n in g.nodes}
        self.versions[version_id] = VersionData(
            version_id=version_id,
            workflow_id=str(uuid.uuid4()),
            graph=g.data(),
            expressions=expressions(g, self.subflows),
            cel_profile=CURRENT_CEL_PROFILE,
            manifests={r: MANIFESTS[r] for r in sorted(refs)},
        )
        return version_id

    async def version(self, tenant_id: str, version_id: str) -> VersionData:
        return self.versions[version_id]

    async def project(self, data: ProjectInput) -> None:
        for row in data.steps:
            self.rows[(row.run_id, row.step_id, row.iteration_key, row.attempt)] = row
        if data.run is not None:
            self.runs[data.run.run_id] = data.run

    def steps(self, run_id: str) -> list[StepRow]:
        return [r for k, r in sorted(self.rows.items()) if k[0] == run_id]


async def in_process(request: dict[str, Any]) -> list[dict[str, Any]]:
    """What the evaluator would answer, computed here: `ipc.evaluate_request` is the child's own work."""
    parsed = ipc.parse_request(request)
    assert isinstance(parsed, ipc.EvaluateRequest)
    reply = ipc.parse_reply(ipc.evaluate_request(parsed), len(parsed.bindings))
    if reply.error is not None:
        return [{"error": reply.error, "message": reply.message}] * len(parsed.bindings)
    return [o.to_json() for o in reply.outcomes]


@asynccontextmanager
async def workers(
    client: Client,
    store: RunStore,
    *,
    plugins: Iterable[Plugin] = (TESTKIT,),
    evaluate: Evaluate | None = in_process,
    runner: WorkflowRunner | None = None,  # tests that inject faults run the workflow outside the sandbox
    cache: int = 1000,  # 0: every workflow task replays the run's whole history
) -> AsyncIterator[None]:
    engine = Worker(
        client,
        task_queue=ENGINE_QUEUE,
        workflows=[RunGraph],
        activities=engine_activities(store, plugins),
        workflow_runner=runner or SandboxedWorkflowRunner(),
        max_cached_workflows=cache,
    )
    async with engine:
        if evaluate is None:  # no evaluator serves the profile
            yield
            return
        async with Worker(client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(evaluate)]):
            yield


async def start(
    client: Client, store: MemoryStore, g: G, trigger: dict[str, Any] | None = None, **options: Any
) -> WorkflowHandle[Any, RunResult]:
    run_id = str(uuid.uuid4())
    run = RunInput(TENANT, run_id, store.add(g), trigger or {}, options.pop("mode", LIVE), **options)
    return await client.start_workflow(RunGraph.run, run, id=run_id, task_queue=ENGINE_QUEUE)


async def run(
    client: Client, store: MemoryStore, g: G, trigger: dict[str, Any] | None = None, **options: Any
) -> RunResult:
    handle = await start(client, store, g, trigger, **options)
    return await handle.result()
