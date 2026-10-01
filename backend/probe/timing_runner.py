"""Throwaway (2b-1b §5.3 CPU check): a workflow runner that records each activation's CPU time (the activating
thread's, `time.thread_time`) and wall time, around the sandboxed runner the engine worker uses. Engine-core's
target is CPU per workflow task; the SDK's deadlock detector times an activation's wall clock against 2 s."""

import time
from typing import Any

from temporalio.worker import WorkflowRunner
from temporalio.worker._workflow_instance import WorkflowInstance, WorkflowInstanceDetails
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

ACTIVATIONS: list[tuple[str, float, float]] = []  # (workflow id, CPU ms, wall ms)


class TimingRunner(WorkflowRunner):
    def __init__(self, inner: WorkflowRunner | None = None) -> None:
        self.inner = inner or SandboxedWorkflowRunner()

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

    def __getattr__(self, name: str) -> Any:  # anything else the worker reads (e.g. the instance for a deadlock trace)
        return getattr(self.inner, name)


def summary() -> dict[str, Any]:
    if not ACTIVATIONS:
        return {}
    cpu = sorted(c for _, c, _ in ACTIVATIONS)
    wall = sorted(w for _, _, w in ACTIVATIONS)
    n = len(cpu)

    def pct(xs: list[float], q: int) -> int:
        return round(xs[min(n - 1, n * q // 100)])

    return {
        "activations": n,
        "cpu_p50": pct(cpu, 50), "cpu_p99": pct(cpu, 99), "cpu_max": round(cpu[-1]),
        "cpu_over_500": sum(c > 500 for c in cpu), "cpu_over_1000": sum(c > 1000 for c in cpu),
        "wall_p99": pct(wall, 99), "wall_max": round(wall[-1]),
        "wall_over_1000": sum(w > 1000 for w in wall), "wall_over_2000": sum(w > 2000 for w in wall),
    }  # fmt: skip
