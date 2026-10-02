# SPDX-License-Identifier: Apache-2.0
"""The focused workflow-task CPU check for 2b-1b's implementation (engine 2b spec §5.3; the owner's M4 condition).
Only what needs the target runner: a workflow task's CPU, and the cause of every failed task, at the heaviest
queued state, with the engine worker at its intended 2 workflow-task slots, one run and four at once.

    bench                         the scheduler alone at the heaviest queued state: a snapshot and a restore, in parts
    exhausted_root many_siblings  the workloads, each copy cancelled after STOP_AFTER continues (CONCURRENT copies)

It times each workflow activation's CPU (the activating thread's) and wall time, around the sandboxed runner the engine
worker uses. Acceptance, asserted (the process exits non-zero otherwise): every activation within CPU_LIMIT_MS of CPU
(engine-core's 1 s), no failed workflow task but one the probe's own cancel explains (a task completing as the cancel
lands, which the server rejects: the next event is the cancel request), and every copy continued at least once."""

import asyncio
import json
import os
import platform
import sys
import time
import uuid
from typing import Any

from temporalio.api.enums.v1 import EventType
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, WorkflowRunner
from temporalio.worker._workflow_instance import WorkflowInstance, WorkflowInstanceDetails
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from dewpoint.apps.worker.activities import cel_activity, engine_activities
from dewpoint.apps.worker.deployment import deployment_config, set_current, this_build
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime import scheduler
from dewpoint.engine.runtime import workflow as run_graph
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, RunInput, cel_queue
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.apps.worker.harness import TENANT, MemoryStore, in_process
from tests.engine.replay.record import executions
from tests.engine.runtime.support import program
from tests.support.graphs import G, ref
from tests.support.keys import FIXTURE_CONVERTER
from tests.support.plugins.testkit import TESTKIT

ECHO, LOOP = "testkit.echo@1", "flow.loop@1"
STOP_AFTER = int(os.environ.get("STOP_AFTER", "40"))
CONCURRENT = int(os.environ.get("CONCURRENT", "1"))
SLOTS = int(os.environ.get("WFT_SLOTS", "2"))
CPU_LIMIT_MS = int(os.environ.get("CPU_LIMIT_MS", "1000"))
TIMEOUT_S = int(os.environ.get("PROBE_TIMEOUT", "1800"))
OUT = os.environ.get("RESULTS", "probe/results_cpu.jsonl")
ACTIVATIONS: list[tuple[str, float, float]] = []  # (workflow id, CPU ms, wall ms)
FAILURES: list[str] = []


class TimingRunner(WorkflowRunner):
    """The sandboxed runner, each activation timed: its thread's CPU and its wall time."""

    def __init__(self, inner: WorkflowRunner) -> None:
        self.inner = inner

    def prepare_workflow(self, defn: Any) -> None:
        self.inner.prepare_workflow(defn)

    def create_instance(self, det: WorkflowInstanceDetails) -> WorkflowInstance:
        return _Timed(self.inner.create_instance(det), det.info.workflow_id)

    def set_worker_level_failure_exception_types(self, types: Any) -> None:
        self.inner.set_worker_level_failure_exception_types(types)


class _Timed(WorkflowInstance):
    def __init__(self, inner: WorkflowInstance, workflow_id: str) -> None:
        self.inner, self.workflow_id = inner, workflow_id

    def activate(self, act: Any) -> Any:
        cpu, wall = time.thread_time(), time.perf_counter()
        try:
            return self.inner.activate(act)
        finally:
            ACTIVATIONS.append(
                (self.workflow_id, (time.thread_time() - cpu) * 1000, (time.perf_counter() - wall) * 1000)
            )

    def get_serialization_context(self, *args: Any, **kwargs: Any) -> Any:
        return self.inner.get_serialization_context(*args, **kwargs)

    def get_external_store_context(self, *args: Any, **kwargs: Any) -> Any:
        return self.inner.get_external_store_context(*args, **kwargs)

    def get_info(self) -> Any:
        return self.inner.get_info()

    def get_thread_id(self) -> int | None:
        return self.inner.get_thread_id()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def siblings(k: int, n: int, *, on_error: str = "fail") -> G:
    """Nested 10 x 10 loops whose body holds k sibling loops of n items (one echo step each): 100 iterations queue k
    loop steps each, the cap deferring nearly all of them (§11.2's counterexample, 482 nodes at k = 240)."""
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": {}}
    for key in ("o", "m"):
        g.node(key, LOOP, {"items": list(range(10)), "concurrency": 10, "collect": ref("item")}, on_error=on_error)
    g.edge("o", "m", "body")
    for j in range(k):
        g.node(f"s{j}", LOOP, {"items": list(range(n)), "concurrency": 1, "collect": ref("item")}, on_error=on_error)
        g.node(f"x{j}", ECHO, {"value": ref("item")}).edge("m", f"s{j}", "body").edge(f"s{j}", f"x{j}", "body")
    return g


WORKLOADS: dict[str, tuple[Any, int]] = {
    "many_siblings": (lambda: siblings(240, 2), scheduler.ITERATION_CAP),  # 240 sibling loops
    "exhausted_root": (lambda: siblings(240, 3, on_error="continue"), 610),  # the root's budget spent early
}


def summary(rows: list[tuple[str, float, float]]) -> dict[str, Any]:
    if not rows:
        return {}
    cpu = sorted(c for _, c, _ in rows)
    wall = sorted(w for _, _, w in rows)
    n = len(cpu)

    def pct(xs: list[float], q: int) -> int:
        return round(xs[min(n - 1, n * q // 100)])

    return {
        "activations": n, "cpu_p50": pct(cpu, 50), "cpu_p99": pct(cpu, 99), "cpu_max": round(cpu[-1]),
        "cpu_over_500": sum(c > 500 for c in cpu), "cpu_over_1000": sum(c > 1000 for c in cpu),
        "wall_p99": pct(wall, 99), "wall_max": round(wall[-1]), "wall_over_2000": sum(w > 2000 for w in wall),
    }  # fmt: skip


def bench() -> dict[str, Any]:
    """The scheduler alone, at 240 sibling loops in nested 10 x 10 loops: a snapshot and a restore, part by part."""
    s = scheduler.Scheduler(program(siblings(240, 2)))
    s.start()
    for _ in range(2):  # the outer and middle loops' iterations open; their bodies queue the sibling loop steps
        for inst in s.take_ready():
            step = s.step(inst)
            if step.key in ("o", "m"):
                s.open_loop(inst, list(step.config["items"]), concurrency=10, stop_on_error=False)
    s.take_settled()
    queued = len(s._ready) + len(s._deferred)

    def parts(gen: Any) -> tuple[list[float], Any]:
        out: list[float] = []
        while True:
            t = time.thread_time()
            try:
                next(gen)
            except StopIteration as done:
                out.append((time.thread_time() - t) * 1000)
                return out, done.value
            out.append((time.thread_time() - t) * 1000)

    snap_parts, data = parts(s.encoding())
    restored = scheduler.Scheduler.restoring(s.program, json.loads(json.dumps(data)))
    restore_parts, _ = parts(restored.decoding(data))
    return {
        "workload": "bench", "queued_loop_steps": queued, "snapshot_ms": round(sum(snap_parts)),
        "snapshot_part_max_ms": round(max(snap_parts)), "restore_ms": round(sum(restore_parts)),
        "restore_part_max_ms": round(max(restore_parts)), "parts": [len(snap_parts), len(restore_parts)],
    }  # fmt: skip


async def stop_after(client: Client, handles: list[Any]) -> set[str]:
    """Once every copy has continued STOP_AFTER times (its latest run id changed as often), cancel each. Returns the
    copies whose cancel was sent."""
    runs: dict[str, set[str]] = {h.id: set() for h in handles}
    started = time.monotonic()
    while time.monotonic() - started < TIMEOUT_S:
        done = 0
        for h in handles:
            d = await client.get_workflow_handle(h.id).describe()
            runs[h.id].add(d.run_id)
            done += d.status is not None and d.status.name != "RUNNING"
        if done == len(handles):
            return set()
        if min(len(r) - 1 for r in runs.values()) >= STOP_AFTER:
            break
        await asyncio.sleep(2)
    cancelled = set()
    for h in handles:
        try:
            await client.get_workflow_handle(h.id).cancel()
            cancelled.add(h.id)
        except Exception as e:  # loud: a copy whose cancel failed runs on
            FAILURES.append(f"cancel of {h.id[-12:]} failed: {type(e).__name__}: {e}")
    return cancelled


def failed_tasks(histories: list[Any], cancelled: set[str]) -> tuple[list[str], int]:
    """Every failed workflow task's cause; and how many aren't explained by the probe's own cancel landing as the
    task completed (the next event is the cancel request, in a run the probe cancelled)."""
    causes, unexcused = [], 0
    for history in histories:
        events = list(history.events)
        for i, e in enumerate(events):
            if e.event_type != EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED:
                continue
            cause = e.workflow_task_failed_event_attributes.cause
            causes.append(f"{history.workflow_id[-12:]}: cause {cause}")
            nxt = events[i + 1].event_type if i + 1 < len(events) else None
            if not (
                history.workflow_id in cancelled and nxt == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CANCEL_REQUESTED
            ):
                unexcused += 1
    return causes, unexcused


async def workload(env: WorkflowEnvironment, name: str) -> dict[str, Any]:
    build, cap = WORKLOADS[name]
    scheduler.ITERATION_CAP = run_graph.ITERATION_CAP = cap  # read as a new run's sandbox imports the workflow
    ACTIVATIONS.clear()
    store = MemoryStore()
    engine = Worker(
        env.client,
        task_queue=ENGINE_QUEUE,
        workflows=[RunGraph, LoopBatch],
        activities=engine_activities(store, [TESTKIT]),
        workflow_runner=TimingRunner(SandboxedWorkflowRunner()),
        max_concurrent_workflow_tasks=SLOTS,
        deployment_config=deployment_config(this_build()),  # as engine_worker's: runs pinned to this build
    )
    evaluator = Worker(
        env.client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process, store)]
    )
    t0 = time.monotonic()
    async with engine, evaluator:
        await set_current(env.client, this_build())
        handles = []
        for _ in range(CONCURRENT):
            version, run_id = store.add(build()), str(uuid.uuid4())
            run = RunInput(TENANT, run_id, version, {}, checkpoint_events=300, drain_events=600)
            handles.append(
                await env.client.start_workflow(
                    RunGraph.run, run, id=run_workflow_id(TENANT, run_id), task_queue=ENGINE_QUEUE
                )
            )
        cancelled = await stop_after(env.client, handles)
        statuses = []
        for h in handles:
            try:
                statuses.append((await asyncio.wait_for(h.result(), TIMEOUT_S)).status)
            except Exception as e:  # a cancelled run ends cancelled, as an error to its caller
                statuses.append(type(e).__name__)
    histories = [x for h in handles for x in await executions(env.client, h.id, h.first_execution_run_id or "")]
    continues = [sum(1 for x in histories if x.workflow_id == h.id) - 1 for h in handles]
    causes, unexcused = failed_tasks(histories, cancelled)
    out = {
        "workload": f"{name} x{CONCURRENT}", "slots": SLOTS, "elapsed_s": round(time.monotonic() - t0),
        "statuses": statuses, "continues": continues, "executions": len(histories), **summary(ACTIVATIONS),
        "failed_tasks": causes, "unexcused_failed_tasks": unexcused,
    }  # fmt: skip
    if out.get("cpu_max", 0) > CPU_LIMIT_MS:
        FAILURES.append(f"{out['workload']}: an activation took {out['cpu_max']} ms of CPU, past {CPU_LIMIT_MS}")
    if unexcused:
        FAILURES.append(f"{out['workload']}: {unexcused} failed workflow task(s) no cancel explains: {causes}")
    if min(continues) < 1:
        FAILURES.append(f"{out['workload']}: a copy never continued: {continues}")
    return out


def save(results: list[dict[str, Any]]) -> None:
    with open(OUT, "a") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")


async def main(names: list[str]) -> None:
    print(platform.platform(), f"cpus {os.cpu_count()}", f"slots {SLOTS}", f"copies {CONCURRENT}", flush=True)
    results = []
    if "bench" in names:
        results.append(bench())
        print(json.dumps(results[-1]), flush=True)
    names = [n for n in names if n != "bench"]
    if names:
        async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as env:
            for name in names:
                results.append(await workload(env, name))
                print(json.dumps(results[-1]), flush=True)
    save(results)
    if FAILURES:
        print("FAILED:", *FAILURES, sep="\n  ", flush=True)
        sys.exit(1)
    print("passed", flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
