# SPDX-License-Identifier: Apache-2.0
"""What `RunGraph` asks of the outside world, as names and dataclasses (spec §2): the version loader, plugin steps,
`cel.evaluate` and the projection. `apps/worker` implements them; the workflow only names them. A plugin step's
activity runs one attempt and writes nothing; the projection is the only activity that writes."""

from dataclasses import dataclass, field
from typing import Any

ENGINE_QUEUE = "dewpoint-engine"
LOAD_VERSION = "dewpoint.load_version"
PROJECT = "dewpoint.project"
CEL_EVALUATE = "cel.evaluate"
LIVE, SIMULATE = "live", "simulate"
APPLIED, SIMULATED, OUTCOME_UNKNOWN = "applied", "simulated", "outcome_unknown"
# In a plugin step's failure details: the activity's own mapping made this failure. `RunGraph` trusts no other failure
# as the node's: the SDK makes its own (a worker shutting down, an exception nothing caught), and those say nothing
# of whether the request went out.
MAPPED = "mapped"


def step_activity(ref: str) -> str:
    """`testkit.echo@1` runs as the activity `testkit.echo.v1`."""
    node_type, version = ref.rsplit("@", 1)
    return f"{node_type}.v{version}"


def cel_queue(profile: str) -> str:
    return f"dewpoint-cel.{profile}"


@dataclass(frozen=True)
class RunInput:
    tenant_id: str
    run_id: str
    version_id: str
    trigger: dict[str, Any]
    mode: str = LIVE  # live | simulate
    max_run_duration_s: float = 30 * 86_400
    cel_schedule_to_start_s: float = 600  # no evaluator for the profile after this: cel_profile_unavailable


@dataclass(frozen=True)
class RunResult:
    status: str  # succeeded | failed | deadline_exceeded | cancelled
    outputs: dict[str, Any] | None = None
    error: dict[str, Any] | None = None  # {code, message}
    iterations: int = 0


@dataclass(frozen=True)
class LoadVersionInput:
    tenant_id: str
    version_id: str


@dataclass(frozen=True)
class VersionData:
    version_id: str
    workflow_id: str
    graph: dict[str, Any]
    expressions: list[dict[str, Any]]
    cel_profile: str
    manifests: dict[str, dict[str, Any]]  # type@version -> manifest, for every node type in the graph


@dataclass(frozen=True)
class StepInput:
    tenant_id: str
    run_id: str
    step_id: str
    node_key: str
    iteration_key: str
    ref: str
    config: dict[str, Any]
    mode: str = LIVE
    attempt: int = 1  # RunGraph counts attempts: each one is its own activity execution


@dataclass(frozen=True)
class StepResult:
    output: dict[str, Any]
    outcome: str = APPLIED


@dataclass(frozen=True)
class CelInput:
    request: dict[str, Any]  # a cel.evaluate.v1 request


@dataclass(frozen=True)
class CelResult:
    outcomes: list[dict[str, Any]]  # one per binding set: {ok} or {error, message}


@dataclass(frozen=True)
class StepRow:
    """One `run_steps` row, keyed (run_id, step_id, iteration_key, attempt)."""

    run_id: str
    step_id: str
    node_key: str
    iteration_key: str
    attempt: int
    status: str  # running | succeeded | failed | cancelled
    started_at: str | None = None
    ended_at: str | None = None
    input_preview: Any = None
    output_preview: Any = None
    error_code: str | None = None
    error_message: str | None = None
    outcome: str | None = None
    cel_mode: str | None = None


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    ended_at: str
    error_code: str | None = None
    error_message: str | None = None
    iterations: int = 0


@dataclass(frozen=True)
class ProjectInput:
    tenant_id: str
    steps: list[StepRow] = field(default_factory=list)
    run: RunSummary | None = None
