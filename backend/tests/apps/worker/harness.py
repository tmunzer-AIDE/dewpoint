# SPDX-License-Identifier: Apache-2.0
"""Run test graphs through `RunGraph` on Temporal's time-skipping test server, with the real step activities, an
in-memory store and an in-process CEL evaluator (the real one needs Linux and its own container)."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from temporalio.client import Client, WorkflowHandle
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker, WorkflowRunner
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from dewpoint.apps.worker.activities import Evaluate, RunStore, cel_activity, engine_activities
from dewpoint.core.claims import secret_index
from dewpoint.core.claims.service import ClaimConflictError, ClaimUnavailableError, NewClaim
from dewpoint.engine import ENGINE_ABI
from dewpoint.engine.cel import ipc
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.validate import SubflowInfo, ValidationContext, validate
from dewpoint.engine.handles import ClaimRef, StoredClaim
from dewpoint.engine.runtime.activities import (
    ENGINE_QUEUE,
    LIVE,
    ProjectInput,
    RunInput,
    RunResult,
    RunStart,
    RunSummary,
    StepRow,
    VersionData,
    cel_queue,
)
from dewpoint.engine.runtime.ids import run_of, run_workflow_id
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from dewpoint.engine.sensitive import MIN_SECRET
from dewpoint.engine.split import split
from dewpoint.sdk import Plugin
from tests.engine.runtime.support import CATALOG, MANIFESTS
from tests.support.graphs import G
from tests.support.plugins.testkit import TESTKIT

TENANT = str(uuid.UUID(int=1))


RESULT_TIMEOUT_S = 60  # the harness's runs are time-skipped: a minute is far more than any needs
# CEL only the evaluator runs, whatever the build (a named time zone, spec §5.5): 1, Paris's hour at 00:00 UTC
# on 1 January. The tests of the `cel.evaluate` path use it now that this build evaluates the rest in-process.
EVALUATOR_ONLY = "timestamp('2026-01-01T00:00:00Z').getHours('Europe/Paris')"


@dataclass(frozen=True)
class HeldClaim:
    """A claim as the store holds it (engine 2b spec §3.1)."""

    tenant_id: str
    owner: str
    root: str
    value: Any
    sensitive_pointers: tuple[str, ...]
    kind: str


@dataclass
class MemoryStore:
    versions: dict[str, VersionData] = field(default_factory=dict)
    rows: dict[tuple[str, str, str, int], StepRow] = field(default_factory=dict)
    runs: dict[str, RunSummary] = field(default_factory=dict)
    subflows: dict[uuid.UUID, SubflowInfo] = field(default_factory=dict)  # what validation sees as published
    starts: dict[str, RunStart] = field(default_factory=dict)  # sub-runs' own rows
    schemas: dict[str, dict[str, Any]] = field(default_factory=dict)  # version -> its output schema
    taints: dict[str, dict[str, Any]] = field(default_factory=dict)  # version -> its outputs' taint (2b spec §4.1)
    claims: dict[str, HeldClaim] = field(default_factory=dict)
    grants: set[tuple[str, str]] = field(default_factory=set)  # (claim, run) (2b spec §3.4)
    index: dict[str, set[str]] = field(default_factory=dict)  # root run -> its secret index (2b spec §3.7)

    def add(self, g: G, workflow_id: uuid.UUID | None = None, *, engine_abi: int = ENGINE_ABI) -> str:
        """Publish `g` as a version, pinned to the sub-flows it runs (as `publish` registered them). `engine_abi`:
        the build that published it, this one unless a test says otherwise."""
        result = validate(g.build(), ValidationContext(catalog=CATALOG, subflows=self.subflows))
        errors = [d.to_json() for d in result.diagnostics if d.severity == "error"]
        assert not errors, errors
        version_id = str(uuid.uuid4())
        refs = {n["type"] for n in g.nodes}
        handler = result.failure_handler_version_id
        self.versions[version_id] = VersionData(
            version_id=version_id,
            workflow_id=str(workflow_id or uuid.uuid4()),
            graph=g.data(),
            expressions=[r.to_json() for r in result.expressions],
            cel_profile=CURRENT_CEL_PROFILE,
            manifests={r: MANIFESTS[r] for r in sorted(refs)},
            subflow_version_ids=dict(result.subflow_pins),
            failure_handler_version_id=str(handler) if handler else None,
            engine_abi=engine_abi,
        )
        self.schemas[version_id] = dict(result.output_schema)
        self.taints[version_id] = dict(result.output_taint)
        return version_id

    def publish(self, g: G, workflow_id: uuid.UUID | None = None, *, engine_abi: int = ENGINE_ABI) -> uuid.UUID:
        """A workflow other graphs can run as a sub-flow or a failure handler: its id. With `workflow_id`, a new
        version of that workflow, which graphs published from now on pin."""
        workflow_id = workflow_id or uuid.uuid4()
        version_id = self.add(g, workflow_id, engine_abi=engine_abi)
        input_schema = g.settings.get("input_schema", {"type": "object"})
        self.subflows[workflow_id] = SubflowInfo(
            workflow_id, uuid.UUID(version_id), input_schema, self.schemas[version_id], self.taints[version_id]
        )
        return workflow_id

    async def version(self, tenant_id: str, version_id: str) -> VersionData:
        if version_id not in self.versions:  # as the database store: a version that isn't there is never retried
            raise ApplicationError(f"version {version_id} not found", type="version_not_found", non_retryable=True)
        return self.versions[version_id]

    async def project(self, data: ProjectInput) -> None:
        if data.start is not None:
            self.starts.setdefault(data.start.run_id, data.start)
        for row in data.steps:
            self.rows[(row.run_id, row.step_id, row.iteration_key, row.attempt)] = row
        if data.run is not None and not (data.run.if_running and data.run.run_id in self.runs):
            self.runs[data.run.run_id] = data.run

    def steps(self, run_id: str) -> list[StepRow]:
        return [r for k, r in sorted(self.rows.items()) if k[0] == run_id]

    # --- claims (2b spec §3), checked as the database store checks them ------------------------------------------

    async def fetch(self, tenant_id: str, run_id: str, claim_id: str) -> StoredClaim:
        held = self.claims.get(claim_id)
        if (
            held is None
            or held.tenant_id != tenant_id
            or (held.owner != run_id and (claim_id, run_id) not in self.grants)
        ):
            raise ClaimUnavailableError("A claim this run may not read, or that doesn't exist.")
        return StoredClaim(held.value, held.sensitive_pointers)

    async def write(
        self, tenant_id: str, claims: Any, *, kind: str, step_id: str | None, iteration_key: str | None
    ) -> None:
        for c in claims:
            assert isinstance(c, NewClaim)
            held = HeldClaim(tenant_id, str(c.owner_run_id), str(c.root_run_id), c.value, c.sensitive_pointers, kind)
            existing = self.claims.get(str(c.id))
            if existing is not None and (existing.value, existing.sensitive_pointers) != (
                c.value,
                c.sensitive_pointers,
            ):
                raise ClaimConflictError("A claim was written again with other content.")
            self.claims[str(c.id)] = held

    async def secrets(self, tenant_id: str, root_run_id: str) -> tuple[str, ...]:
        return tuple(sorted(self.index.get(root_run_id, set())))

    async def remember(self, tenant_id: str, root_run_id: str, strings: Any) -> None:
        merged = self.index.get(root_run_id, set()) | {s for s in strings if len(s) >= MIN_SECRET}
        secret_index.check(sorted(merged))  # past its bounds, nothing changes (2b spec §3.7)
        self.index[root_run_id] = merged

    def claim(self, value: Any, *, owner: str, tainted: bool) -> dict[str, Any]:
        """A claim made outside any run, for a test to hand one: its handle."""
        claim_id = str(uuid.uuid4())
        self.claims[claim_id] = HeldClaim(TENANT, owner, owner, value, ("",) if tainted else (), "input")
        return ClaimRef(claim_id).to_json()

    def admit(self, trigger: dict[str, Any], schema: Any, run_id: str) -> Any:
        """`trigger` split as admission splits it (2b spec §3.5), its claims owned by `run_id`: the envelope."""
        done = split(trigger, schema, lambda pointer: str(uuid.uuid4()))
        for c in done.claims:
            sensitive = ("",) if c.tainted else ()
            self.claims[c.id] = HeldClaim(TENANT, run_id, run_id, c.value, sensitive, "input")
        self.index.setdefault(run_id, set()).update(done.secrets)  # admission seeds the index
        return done.envelope


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
        workflows=[RunGraph, LoopBatch],
        activities=engine_activities(store, plugins),
        workflow_runner=runner or SandboxedWorkflowRunner(),
        max_cached_workflows=cache,
    )
    async with engine:
        if evaluate is None:  # no evaluator serves the profile
            yield
            return
        async with Worker(
            client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(evaluate, store)]
        ):
            yield


async def start(
    client: Client,
    store: MemoryStore,
    g: G,
    trigger: dict[str, Any] | None = None,
    *,
    claimed: bool = False,
    **options: Any,
) -> WorkflowHandle[Any, RunResult]:
    """`claimed`: the trigger is split as admission splits it (2b spec §3.5), its sensitive values handles."""
    run_id = str(uuid.uuid4())
    if claimed:
        trigger = store.admit(trigger or {}, g.settings.get("input_schema"), run_id)
    return await start_version(client, store.add(g), trigger, run_id=run_id, **options)


async def start_version(
    client: Client, version_id: str, trigger: dict[str, Any] | None = None, *, run_id: str | None = None, **options: Any
) -> WorkflowHandle[Any, RunResult]:
    """A run of a version the store already has."""
    run_id = run_id or str(uuid.uuid4())
    run = RunInput(TENANT, run_id, version_id, trigger or {}, options.pop("mode", LIVE), **options)
    return await client.start_workflow(RunGraph.run, run, id=run_workflow_id(TENANT, run_id), task_queue=ENGINE_QUEUE)


def run_id_of(workflow: WorkflowHandle[Any, Any] | str) -> str:
    """The run a run's handle or workflow id names, a sub-run's too: its id is built from the tenant and the run
    (engine 2b spec §6.1)."""
    workflow_id = workflow if isinstance(workflow, str) else workflow.id
    run_id = run_of(workflow_id)
    assert run_id is not None, workflow_id
    return run_id


async def run(
    client: Client, store: MemoryStore, g: G, trigger: dict[str, Any] | None = None, **options: Any
) -> RunResult:
    """A run to its end: a run that hangs fails its test instead of stalling the suite (2a-3a's final review, M6)."""
    handle = await start(client, store, g, trigger, **options)
    return await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
