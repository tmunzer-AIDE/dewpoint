# SPDX-License-Identifier: Apache-2.0
"""What `RunGraph` asks of the outside world, as names and dataclasses (spec §2): the version loader, plugin steps,
`cel.evaluate` and the projection. `apps/worker` implements them; the workflow only names them. A plugin step's
activity runs one attempt and writes nothing; the projection is the only activity that writes.

Also the contracts between executions (2a-3b): a child's input and result (a sub-flow or failure handler is a
`RunGraph`; a loop batch is a `LoopBatch`), and the budget signals a child and its parent exchange."""

from dataclasses import dataclass, field
from typing import Any

from dewpoint.engine import ENGINE_ABI

ENGINE_QUEUE = "dewpoint-engine"
LOAD_VERSION = "dewpoint.load_version"
PROJECT = "dewpoint.project"
CEL_EVALUATE = "cel.evaluate"
CLAIMS_DERIVE = "claims.derive"
CLAIMS_CHILD_INPUT = "claims.child_input"
CLAIMS_GRANT = "claims.grant"
CLAIMS_MESSAGE = "claims.message"
LIVE, SIMULATE = "live", "simulate"
APPLIED, SIMULATED, OUTCOME_UNKNOWN = "applied", "simulated", "outcome_unknown"
SUBFLOW, FAILURE_HANDLER, BATCH = "subflow", "failure_handler", "batch"  # the kinds of child execution
REQUEST_BUDGET, BUDGET = (
    "request_budget",
    "budget",
)  # child -> parent (child, key, need, want, held); parent -> child (key, granted)
CHECKPOINT_EVENTS = 2_000  # continue-as-new at the next quiescent point after this many events (spec §6)
DRAIN_EVENTS = 4_000  # drain mode from this many events, or when Temporal suggests it
# In a plugin step's failure details: the activity's own mapping made this failure. `RunGraph` trusts no other failure
# as the node's: the SDK makes its own (a worker shutting down, an exception nothing caught), and those say nothing
# of whether the request went out.
MAPPED = "mapped"


def step_activity(ref: str) -> str:
    """`testkit.echo@1` runs as the activity `testkit.echo.v1`."""
    node_type, version = ref.rsplit("@", 1)
    return f"{node_type}.v{version}"


def cel_queue(profile: str) -> str:
    """The queue of `cel.evaluate` for a profile, and for this build's engine ABI. CEL queues are outside the engine
    deployment, so the ABI keeps each build's requests to CEL workers that can read them: from ABI 5 on a request is
    encrypted, which a build before it can't read (engine 2b spec §6.6). Builds before ABI 5 poll
    `dewpoint-cel.<profile>`."""
    return f"dewpoint-cel.abi{ENGINE_ABI}.{profile}"


@dataclass(frozen=True)
class Parent:
    """How a child execution reaches its parent, and what it inherits from it."""

    workflow_id: str  # where its budget requests go
    run_id: str  # the parent run: a sub-run's row points at it
    step_id: str  # the step that started it; empty for a failure handler
    iteration_key: str
    kind: str  # subflow | failure_handler | batch
    deadline: str  # ISO 8601: the logical run's deadline, which children share (a failure handler gets its own)
    grant: int  # the iterations its parent reserved for it
    depth: int = 1  # sub-flows nest at most 5 deep (spec §6)
    root_run_id: str = ""  # the tree's root run: what its claims record (engine 2b spec §3.1)


@dataclass(frozen=True)
class RunInput:
    tenant_id: str
    run_id: str
    version_id: str
    trigger: dict[str, Any]
    mode: str = LIVE  # live | simulate
    max_run_duration_s: float = 30 * 86_400
    cel_schedule_to_start_s: float = 600  # no evaluator for the profile after this: cel_profile_unavailable
    parent: Parent | None = None  # a sub-flow or a failure handler; None for a run the dispatcher started
    workflow_id: str = ""  # a sub-run's workflow: it writes its own row with it, before its version loads
    snapshot: dict[str, Any] | None = None  # a continued run: where it carries on (spec §6, `snapshot_format` 1)
    checkpoint_events: int = CHECKPOINT_EVENTS
    drain_events: int = DRAIN_EVENTS
    iterations: int = 0  # a continued run: what it had used, readable even when its snapshot isn't


@dataclass(frozen=True)
class RunResult:
    status: str  # succeeded | failed | deadline_exceeded | cancelled
    outputs: dict[str, Any] | None = None
    error: dict[str, Any] | None = None  # {code, message}
    iterations: int = 0


@dataclass(frozen=True)
class BatchInput:
    """A slice of a loop, for a `LoopBatch` child: items `offset` .. `offset + len(items)`. It reads the loop's
    enclosing scopes as `outer` (outermost first, the loop's own scope last) and writes its rows into `run_id`."""

    tenant_id: str
    run_id: str
    version_id: str
    loop_step: str
    outer: list[dict[str, Any]]  # {key, results, item, index} per enclosing scope
    items: list[Any]
    offset: int
    concurrency: int
    stop_on_error: bool
    trigger: dict[str, Any]
    variables: dict[str, Any]
    run_started_at: str
    parent: Parent
    mode: str = LIVE
    cel_schedule_to_start_s: float = 600
    snapshot: dict[str, Any] | None = None
    checkpoint_events: int = CHECKPOINT_EVENTS
    drain_events: int = DRAIN_EVENTS
    iterations: int = 0  # a continued batch: what it had used, readable even when its snapshot isn't


@dataclass(frozen=True)
class BatchResult:
    collected: list[Any]
    failures: list[dict[str, Any]]
    stopped: dict[str, Any] | None = None  # the failure that stopped the slice (`on_item_error: stop`)
    end: dict[str, Any] | None = None  # the run ended inside the batch (a fail or stop node, the deadline)
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
    subflow_version_ids: dict[str, str] = field(default_factory=dict)  # run_workflow node id -> pinned version id
    failure_handler_version_id: str | None = None
    engine_abi: int | None = None  # the ABI it was published for; None only in histories recorded before 2a-3c


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
    root_run_id: str = ""  # the run tree's root: its claims record it, and its secret index masks (engine 2b §3.7)


@dataclass(frozen=True)
class StepResult:
    output: dict[str, Any]
    outcome: str = APPLIED


@dataclass(frozen=True)
class Claiming:
    """What `cel.evaluate` does with handles and results (engine 2b spec §3.3, §4.2): it resolves the handles among
    the bindings, checked against their rows for the run its workflow id names, and claims a result that read
    sensitive data, or one whose expression does (`tainted`), under ids derived from `seed` (the same on a retry). A
    declassified decision (`decision`) comes back plain."""

    root_run_id: str
    seed: str
    tainted: bool = False
    decision: bool = False
    step_id: str | None = None  # the producer, recorded on the claim for tracing
    iteration_key: str | None = None


@dataclass(frozen=True)
class CelInput:
    request: dict[str, Any]  # a cel.evaluate.v1 request; its bindings may hold handles
    claims: Claiming | None = None
    template: list[Any] | None = None  # a template whose parts are handles: its parts (`resolve.Part`), joined there
    # A filter over claims or with a sensitive predicate, run whole there (engine 2b spec §4.4): {items, record}; the
    # request's one binding set is everything but the item's
    filter: dict[str, Any] | None = None


@dataclass(frozen=True)
class DeriveInput:
    """A handle the workflow can't hold or judge as it is (engine 2b spec §3.2): whether it addresses anything, and
    null, and past POINTER_MAX, what it addresses as a claim of its own, owned by the run the activity's workflow id
    names, with the source's taint for that part."""

    handle: dict[str, Any]
    claim_id: str  # the workflow's: the same on a retry
    root_run_id: str
    step_id: str | None = None
    iteration_key: str | None = None


@dataclass(frozen=True)
class ChildInput:
    """A sub-flow's input, split as a trigger is before its parent starts it (engine 2b spec §3.4, §3.5): checked
    against the child version's input schema, its values resolved; the parent's handles left in place and granted to
    the child; its other sensitive, undeclared or large parts claimed for the child."""

    child_run_id: str
    version_id: str
    value: dict[str, Any]
    root_run_id: str


@dataclass(frozen=True)
class ChildInputResult:
    trigger: dict[str, Any] | None = None  # the envelope the child starts with
    reasons: list[str] = field(default_factory=list)  # refused: what the input breaks


@dataclass(frozen=True)
class GrantInput:
    """The handles in `value`, and the claims they nest, granted by the run the activity's workflow id names to
    `to_run_id`: its parent or its child (engine 2b spec §3.4)."""

    to_run_id: str
    value: Any
    root_run_id: str


@dataclass(frozen=True)
class MessageInput:
    """A failure's message built from data (engine 2b spec §3.7): text, or a handle, which the activity resolves and
    masks against the run tree's secret index."""

    value: Any
    root_run_id: str


@dataclass(frozen=True)
class MessageResult:
    text: str


@dataclass(frozen=True)
class DeriveResult:
    """What the handle addresses, as the workflow may hold it: the same handle within POINTER_MAX, a derived claim's
    past it; None for null. `present` False: the pointer addresses nothing."""

    handle: dict[str, Any] | None
    present: bool = True


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
    if_running: bool = False  # a parent writing the end of a child that ended without one: never over the child's own


@dataclass(frozen=True)
class RunStart:
    """A sub-run's own `runs` row: written with its first projection, before any of its steps."""

    run_id: str
    workflow_id: str
    version_id: str
    mode: str
    parent_run_id: str
    parent_step_id: str | None
    parent_iteration_key: str
    kind: str  # subflow | failure_handler
    started_at: str

    @classmethod
    def of(cls, run: "RunInput", started_at: str) -> "RunStart":
        """A sub-run's row, from its input: what its own first projection writes, and what its parent writes for it
        when it ended before writing one."""
        if run.parent is None or not run.workflow_id:
            raise ValueError("a root run has no sub-run row")
        return cls(
            run_id=run.run_id,
            workflow_id=run.workflow_id,
            version_id=run.version_id,
            mode=run.mode,
            parent_run_id=run.parent.run_id,
            parent_step_id=run.parent.step_id or None,
            parent_iteration_key=run.parent.iteration_key,
            kind=run.parent.kind,
            started_at=started_at,
        )


@dataclass(frozen=True)
class ProjectInput:
    tenant_id: str
    steps: list[StepRow] = field(default_factory=list)
    run: RunSummary | None = None
    start: RunStart | None = None
    root_run_id: str = ""  # the run tree's root: its secret index masks every row (engine 2b spec §3.7)
