# SPDX-License-Identifier: Apache-2.0
"""What every execution of a graph shares (spec §6): a run, a sub-flow and a failure handler (`RunGraph`), and a loop
batch (`LoopBatch`). Each drives its scheduler until it ends: every ready step runs as one future (its values
resolved, then a control node decides, a plugin step runs as its activity, a sub-flow or a batch runs as a child).
At most IN_FLIGHT_CAP futures are outstanding, plus one projection; completions are applied in (scope, topological)
order, so a replay applies them the same way. Nothing else creates concurrency.

Children draw their iterations from their parent's budget (spec §6): a child signals `request_budget` to its parent,
which answers `budget` in the order the requests reach its history. An execution continues-as-new at a quiescent
point (no activity and no child outstanding): opportunistically past `checkpoint_events`, or after draining past
`drain_events` (or when Temporal suggests it), when it starts nothing new and waits for what's outstanding. A timer
isn't outstanding: its wake time goes into the snapshot, and the continued run re-arms it."""

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError, TerminatedError, TimeoutError
from temporalio.exceptions import CancelledError as ActivityCancelled

with workflow.unsafe.imports_passed_through():
    from dewpoint.engine.canonical import canonical_json
    from dewpoint.engine.cel import evaluate as cel
    from dewpoint.engine.cel.ipc import EvaluateRequest
    from dewpoint.engine.cel.profile import LOCAL_CEL_PROFILE
    from dewpoint.engine.cel.record import ExpressionRecord
    from dewpoint.engine.cel.route import YieldBudget
    from dewpoint.engine.graph.values import CelValue, RefValue, TemplateValue
    from dewpoint.engine.handles import CLAIM_UNAVAILABLE, MISSING, ClaimRef, contains_marker
    from dewpoint.engine.registry import control
    from dewpoint.engine.runtime import nodes, resolve
    from dewpoint.engine.runtime.activities import (
        BATCH,
        BUDGET,
        CEL_EVALUATE,
        CLAIMS_CHILD_INPUT,
        CLAIMS_DERIVE,
        CLAIMS_GRANT,
        ENGINE_QUEUE,
        MAPPED,
        OUTCOME_UNKNOWN,
        PROJECT,
        REQUEST_BUDGET,
        SUBFLOW,
        BatchInput,
        BatchResult,
        CelInput,
        CelResult,
        ChildInput,
        ChildInputResult,
        Claiming,
        DeriveInput,
        DeriveResult,
        GrantInput,
        Parent,
        ProjectInput,
        RunInput,
        RunResult,
        RunStart,
        RunSummary,
        StepInput,
        StepResult,
        StepRow,
        cel_queue,
        step_activity,
    )
    from dewpoint.engine.runtime.budget import LOCAL, Need
    from dewpoint.engine.runtime.ids import ITEM_CAP_MAX, batch_workflow_id, run_workflow_id
    from dewpoint.engine.runtime.program import Program, Step
    from dewpoint.engine.runtime.projection import (
        preview,
        sanitize,
        storable,
    )
    from dewpoint.engine.runtime.scheduler import (
        CAP_MESSAGE,
        ITERATION_CAP_EXCEEDED,
        SNAPSHOT_FORMAT,
        Batch,
        BatchOutcome,
        Collect,
        Failure,
        Instance,
        RunEnd,
        Scheduler,
        ScopeKey,
        iteration_key,
    )
    from dewpoint.engine.runtime.size import (
        BATCH_ITEM_TOO_LARGE,
        PAYLOAD_TOO_LARGE,
        STEP_INPUT_TOO_LARGE,
        SUBFLOW_INPUT_TOO_LARGE,
        encoded_bytes,
        fits,
        payload_bytes,
    )
    from dewpoint.engine.taint import Shape, from_schema, tainted_positions

IN_FLIGHT_CAP = 100  # activities and child workflows outstanding per execution (spec §6)
PROJECT_BYTES = 256 * 1024  # a projection's rows at most, as JSON: far below Temporal's 2 MiB payload limit
CEL_BATCH = 1_000  # binding sets per cel.evaluate request
CEL_REQUEST_BYTES = 1_835_008  # a cel.evaluate request's JSON bytes, a margin under Temporal's 2 MiB limit (#15)
REQUEST_TOO_LARGE = "The values this expression reads are too large to send to the CEL evaluator (over 1.75 MiB)."
FILTER_INLINE = 1_000  # a filter's items the workflow may evaluate itself; a larger list goes to cel.evaluate (spec §6)
SUBFLOW_GRANT = 1_000  # a sub-flow's initial grant (spec §6)
MAX_DEPTH = 5  # sub-flows nest at most this deep (spec §6; publish checks it too)
DEADLINE_EXCEEDED = "deadline_exceeded"
VERSION_UNUSABLE = "version_unusable"  # this build can't load or compile the version
INTERNAL_ERROR = "internal_error"  # an exception in workflow code: a bug
TERMINATED = "terminated"  # a child ended by an operator, outside Dewpoint: it never reported
NODE_TYPE_UNAVAILABLE = "node_type_unavailable"  # the registry has it, but this build's workers don't run it
CANCELLED = Failure("cancelled", "The run was cancelled.")
AMBIGUOUS = "ambiguous"  # a manifest's side_effect: the request may have been sent
CONTINUE = "continue"  # `_drive`'s answer when the execution continues-as-new
CLAIM_REFUSED = "A claim this run may not read, or that doesn't exist."
INPUT_INVALID = "input_invalid"  # a sub-flow's input that doesn't match its schema, found where it's resolved


class ExposedError(Exception):
    """Plain data arrived where a schema puts sensitive data: the boundary failed, and the run fails `internal_error`
    rather than use it (engine 2b spec §3.6)."""


@dataclass(frozen=True)
class _Effect:
    """How a future ended; applied to the scheduler in order."""

    output: Any = None
    ports: tuple[str, ...] | None = None
    variables: Mapping[str, Any] | None = None
    failure: Failure | None = None
    end: RunEnd | None = None
    loop: nodes.LoopStart | None = None
    collected: Any = None
    cel_mode: str | None = None
    batch: BatchOutcome | None = None


def _attempt_failed(
    error: ActivityError, key: str, attempt: int, *, ambiguous: bool, non_retryable: Sequence[str]
) -> tuple[Failure, str | None, bool]:
    """How one attempt failed: (the failure, its outcome, whether another attempt may follow)."""
    cause = error.cause
    if isinstance(cause, ApplicationError) and cause.type == "NotFoundError":  # the SDK: no such activity here
        return Failure(NODE_TYPE_UNAVAILABLE, f"No worker of this build runs `{key}`'s node type.", attempt), None, True
    details = cause.details[0] if isinstance(cause, ApplicationError) and cause.details else None
    if isinstance(cause, ApplicationError) and isinstance(details, dict) and details.get(MAPPED) is True:
        code = cause.type or "error"  # the node's own error, mapped by the activity
        retryable = not cause.non_retryable and code not in non_retryable
        return Failure(code, cause.message, attempt), details.get("outcome"), retryable
    # Anything else: a timeout, a worker lost or shutting down, a failure the activity never mapped. The node may have
    # done its work, and nothing that saw what happened described it.
    code, message = (
        (cel.TIMEOUT, f"`{key}` didn't finish in time.")
        if isinstance(cause, TimeoutError)
        else (
            "error",
            f"`{key}` ended without a result.",
        )
    )
    if ambiguous:  # the request may have been sent: never repeat it (parent §6.6)
        return Failure(code, f"{message} Its request may have been sent.", attempt), OUTCOME_UNKNOWN, False
    return Failure(code, message, attempt), None, True


def _cancelled(e: BaseException) -> bool:
    """Our own cancel, as the SDK reports it: `CancelledError` when the awaited activity had already finished in the
    same activation, an `ActivityError` caused by Temporal's `CancelledError` otherwise."""
    return isinstance(e, asyncio.CancelledError) or (
        isinstance(e, ActivityError) and isinstance(e.cause, ActivityCancelled)
    )


def _unloadable(e: BaseException) -> str:
    """What a run whose version didn't load says. The loader's own refusal (`version_unusable`: a version of another
    engine ABI) is written for users; any other error's text may quote the version, so the projection names only its
    type, and the worker's log has the rest."""
    refusal = e.cause if isinstance(e, ActivityError) else e  # a local activity's failure comes unwrapped
    if isinstance(refusal, ApplicationError) and refusal.type == VERSION_UNUSABLE:
        return refusal.message
    return f"This build can't run the version ({type(e).__name__}); the worker's log has the details."


def _backoff(retry: Mapping[str, Any], attempt: int) -> float:
    """Seconds before attempt `attempt + 1`, from the manifest's retry settings."""
    delay = float(retry["initial_interval_s"]) * float(retry["backoff"]) ** (attempt - 1)
    return min(delay, float(retry["max_interval_s"]))


async def _landed(work: "asyncio.Future[Any]") -> bool:
    """Wait for `work` whatever cancels arrive meanwhile: it isn't cancelled, and it completes. True when a cancel
    arrived."""
    cancelled = False
    while True:
        try:
            await asyncio.shield(work)
            return cancelled
        except asyncio.CancelledError:
            if work.cancelled():
                raise
            cancelled = True


def child_options(child_id: str) -> dict[str, Any]:
    """Every child: on the engine queue, started once, and never outliving its parent. A cancelled child reports
    back before the parent carries on, so its iterations are always counted."""
    return {
        "id": child_id,
        "task_queue": ENGINE_QUEUE,
        "parent_close_policy": workflow.ParentClosePolicy.REQUEST_CANCEL,
        "cancellation_type": workflow.ChildWorkflowCancellationType.WAIT_CANCELLATION_COMPLETED,
        "retry_policy": RetryPolicy(maximum_attempts=1),
    }


def _decision(owner: Step | None, pointer: str) -> bool:
    """Whether a field's value is a decision (engine 2b spec §4.3): over sensitive data, the activity that computes it
    gives it back plain. A branch's condition, a switch case's `when`."""
    if owner is None:
        return False
    if owner.ref == "flow.if@1":
        return pointer == "/condition"
    parts = pointer.split("/")
    return owner.ref == "flow.switch@1" and len(parts) == 4 and parts[1] == "cases" and parts[3] == "when"


def _json_bytes(value: Any) -> int:
    """The JSON bytes Temporal's payload converter writes for `value`: what the SDK checks against its payload limit,
    before any codec (#15)."""
    return len(workflow.payload_converter().to_payloads([value])[0].data)


class Execution:
    """The drive loop and everything it runs. A subclass sets the context (`_context`) and a scheduler, then drives."""

    program: Program
    sched: Scheduler

    def __init__(self) -> None:
        self._yield = YieldBudget()  # the local evaluations of the current workflow task (spec §5.6)
        self._yield_task = -1  # the history length that workflow task started with
        self._startup_task = workflow.info().get_current_history_length()  # this execution's first: it starts it
        self._yield_timer: asyncio.Task[None] | None = None  # the one yield point every waiter shares
        self._rows: dict[tuple[str, str, int], StepRow] = {}  # queued for the next projection, per attempt
        self._started: dict[Instance, str] = {}
        self._cel_modes: dict[Instance, str] = {}
        self._projects = 0
        self._timers: dict[Instance, datetime] = {}  # a timer step asleep -> its wake time
        self._resume: list[Instance] = []  # timer steps a snapshot carried over: they re-arm first
        self._mail: list[Need] = []  # children's budget requests, as their signals arrived
        self._answers: list[tuple[str, int]] = []  # our parent's answers
        self._ask: str | None = None  # the request we sent our parent, unanswered
        self._asks = 0
        self._dirty = False  # a unit changed the budget: serve it
        self._filters: dict[str, asyncio.Future[int]] = {}  # a filter's budget need -> its answer
        self._signals: list[asyncio.Task[None]] = []
        self._cancelled = 0
        self._batches: dict[
            tuple[Instance, int], Batch
        ] = {}  # a batch unit's key -> the batch (its items aren't hashable)
        self._drained: dict[str, Any] = {}  # what draining waited for, and added: history events and bytes
        self._draining = False  # drain mode: nothing new starts until the execution continues-as-new
        self._shapes: dict[str, Shape] = {}  # a node type's output taint (`_output_shape`)

    # --- the budget signals ----------------------------------------------------------------------------------------

    @workflow.signal(name=REQUEST_BUDGET)
    def request_budget(self, child: str, key: str, need: int, want: int, held: int) -> None:
        self._mail.append(Need(child, key, need, want, held))

    @workflow.signal(name=BUDGET)
    def budget(self, key: str, granted: int) -> None:
        self._answers.append((key, granted))

    # --- the context -----------------------------------------------------------------------------------------------

    def _context(
        self,
        *,
        tenant_id: str,
        run_id: str,
        version_id: str,
        mode: str,
        trigger: dict[str, Any],
        cel_schedule_to_start_s: float,
        max_run_duration_s: float,
        parent: Parent | None,
        run_started_at: datetime,
        deadline: datetime,
        checkpoint_events: int,
        drain_events: int,
    ) -> None:
        self.tenant_id, self.run_id, self.version_id, self.mode = tenant_id, run_id, version_id, mode
        self.trigger = trigger
        self.cel_schedule_to_start_s = cel_schedule_to_start_s
        self.max_run_duration_s = max_run_duration_s
        self.parent = parent
        self.depth = parent.depth if parent is not None else 0
        self.run_started_at, self.deadline = run_started_at, deadline
        self.checkpoint_events, self.drain_events = checkpoint_events, drain_events
        self.vars: dict[str, Any] = {}
        # the tree's root run: what the claims this execution makes record (engine 2b spec §3.1)
        self.root_run_id = parent.root_run_id if parent is not None and parent.root_run_id else run_id

    # --- the scheduler loop ----------------------------------------------------------------------------------------

    async def _drive(self) -> str | None:
        """Drive the scheduler until the execution ends (None), or until it continues-as-new (CONTINUE)."""
        tasks: dict[tuple[Any, ...], asyncio.Task[_Effect | None]] = {}
        waiting: list[tuple[Any, ...]] = []
        for inst in self._resume:
            tasks[("step", inst)] = asyncio.create_task(self._timer(inst, self._timers[inst]))
        self._resume = []
        clock = asyncio.create_task(asyncio.sleep(max(0.0, (self.deadline - workflow.now()).total_seconds())))
        try:
            while self.sched.ended is None:
                self._serve_budget()
                if not self._draining:
                    waiting += [("step", i) for i in self.sched.take_ready()]
                    waiting += [("collect", c) for c in self.sched.take_collects()]
                    for b in self.sched.take_batches():
                        self._batches[(b.loop, b.start)] = b
                        waiting.append(("batch", b.loop, b.start))
                for inst in self.sched.take_cancels():
                    self._timers.pop(inst, None)
                    for key in [k for k in tasks if k[0] in ("step", "batch") and self._owner(k) == inst]:
                        task = tasks.pop(key)
                        task.cancel()  # a child reports back first: the unit stays outstanding until it does
                        self._cancelled += 1
                        tasks[("cancelled", self._cancelled)] = task
                waiting = [w for w in waiting if not self._gone(w)]
                waiting.sort(key=self._rank)
                self._queue_settled()
                if self.sched.ended is not None:
                    break
                # Before anything new starts: is this a point where continue-as-new may happen (spec §6)?
                length = workflow.info().get_current_history_length()
                if not self._draining and self._drain_due():
                    self._draining = True  # start nothing new; continue-as-new once what's outstanding settles
                    self._drained = {
                        "at": workflow.now().isoformat(),
                        "events": [length],
                        "bytes": [workflow.info().get_current_history_size()],
                        "units": self._units(tasks),  # what the drain waits for
                    }
                if (self._draining or length >= self.checkpoint_events) and self._quiescent(tasks):
                    if self._draining:  # measured, for the headroom (spec §6): what draining added
                        self._drained["events"].append(length)
                        self._drained["bytes"].append(workflow.info().get_current_history_size())
                    await self._settle_for_continue(tasks)
                    self.sched.give_back(
                        [w[1] for w in waiting if w[0] == "step"],
                        [w[1] for w in waiting if w[0] == "collect"],
                        [self._batches.pop((w[1], w[2])) for w in waiting if w[0] == "batch"],
                    )
                    return CONTINUE
                while not self._draining and waiting and self._in_flight(tasks) < IN_FLIGHT_CAP:
                    unit = waiting.pop(0)
                    tasks[unit] = asyncio.create_task(self._unit(unit))
                if self._rows and not any(key[0] == "project" for key in tasks):  # one at a time: rows wait for it
                    self._projects += 1
                    tasks[("project", self._projects)] = asyncio.create_task(self._project(self._take_rows()))
                if not tasks and self._ask is None:  # waiting for our parent's answer isn't stuck: nothing else is
                    raise RuntimeError("nothing is running and the run hasn't ended")
                wake = asyncio.create_task(
                    workflow.wait_condition(
                        lambda: (
                            bool(self._mail or self._answers or self._dirty)
                            or (not self._draining and self._drain_due())
                        )
                    )
                )
                done, _ = await workflow.wait([*tasks.values(), clock, wake], return_when=asyncio.FIRST_COMPLETED)
                wake.cancel()
                if clock in done:
                    self.sched.end(
                        RunEnd(DEADLINE_EXCEEDED, Failure(DEADLINE_EXCEEDED, "The run passed its deadline."))
                    )
                    break
                for key in sorted((k for k, t in tasks.items() if t in done), key=self._rank):
                    task = tasks.pop(key)
                    if key[0] == "cancelled" and task.cancelled():
                        continue  # a unit we cancelled ended so: its cancel isn't this execution's
                    effect = task.result()
                    if effect is not None and key[0] != "cancelled":
                        self._apply(key, effect)
        finally:
            clock.cancel()
            for key, task in tasks.items():
                if key[0] not in ("project", "cancelled"):
                    task.cancel()
            # Each outstanding unit reports back first, a cancelled child included. A cancel of this execution meanwhile
            # mustn't reach them again: Temporal refuses a second cancel of the same child, and then this workflow
            # task could never complete. An end already decided stands.
            await _landed(asyncio.gather(*tasks.values(), return_exceptions=True))
        return None

    def _drain_due(self) -> bool:
        """Past `drain_events`, or Temporal suggests continuing. The drive loop wakes for it too, so a drain begins at
        the first workflow task past the threshold, not at the next unit's end."""
        info = workflow.info()
        return info.get_current_history_length() >= self.drain_events or info.is_continue_as_new_suggested()

    def _units(self, tasks: Mapping[tuple[Any, ...], asyncio.Task[Any]]) -> dict[str, int]:
        """What's outstanding, by kind: activities, children, timers, values (CEL, filters), collects, the
        projection, cancelled units."""
        kinds: dict[str, int] = {}
        for key in tasks:
            kind = self._kind(key)
            kinds[kind] = kinds.get(kind, 0) + 1
        return dict(sorted(kinds.items()))

    def _kind(self, key: tuple[Any, ...]) -> str:
        if key[0] == "batch":
            return "children"
        if key[0] != "step":
            return str(key[0])
        if key[1] in self._timers:
            return "timers"
        step = self.sched.step(key[1])
        if not step.control:
            return "activities"
        return "children" if step.ref == control.RUN_WORKFLOW else "values"

    def _quiescent(self, tasks: Mapping[tuple[Any, ...], asyncio.Task[Any]]) -> bool:
        """No activity and no child outstanding, and no request to or from a parent or child: a sleeping timer step
        doesn't count, nor a projection (it's written before the run continues)."""
        idle = all(k[0] == "project" or (k[0] == "step" and k[1] in self._timers) for k in tasks)
        return idle and not self.sched.budget.asking and not self._mail and not self._answers

    async def _settle_for_continue(self, tasks: dict[tuple[Any, ...], asyncio.Task[Any]]) -> None:
        """Continue-as-new: the sleeping timer steps stop here (their wake times go into the snapshot), and the
        projection in flight lands, whatever cancels arrive meanwhile. A cancel then ends the execution instead
        (raised once it has landed): a continued run wouldn't inherit it."""
        for key, task in tasks.items():
            if key[0] == "step":
                task.cancel()
        cancelled = await _landed(asyncio.gather(*tasks.values(), return_exceptions=True))
        tasks.clear()
        if cancelled:
            raise asyncio.CancelledError

    @staticmethod
    def _in_flight(tasks: Mapping[tuple[Any, ...], asyncio.Task[Any]]) -> int:
        """The units outstanding: the in-flight cap counts them, not the one projection beside them (spec §6)."""
        return sum(1 for key in tasks if key[0] != "project")

    def _owner(self, key: tuple[Any, ...]) -> Instance:
        owner: Instance = key[1]  # a step's instance, or a batch's loop
        return owner

    def _rank(self, key: tuple[Any, ...]) -> tuple[Any, ...]:
        if key[0] == "step":
            return (self.sched.order(key[1]), 0)
        if key[0] == "collect":
            c: Collect = key[1]
            return (self.sched.order(Instance(c.scope, c.loop.step)), 1)
        if key[0] == "batch":
            return (self.sched.order(key[1]), 2, key[2])
        return ((), 3, key[1])

    def _gone(self, unit: tuple[Any, ...]) -> bool:
        """A queued unit whose scope has ended since: it never starts."""
        key = unit[1].scope  # a step's, a batch's loop's, or a collect's own
        scope = self.sched.scopes.get(key)
        return scope is None or scope.failure is not None

    async def _unit(self, key: tuple[Any, ...]) -> _Effect | None:
        if key[0] == "step":
            self._started[key[1]] = workflow.now().isoformat()
            return await self._step(key[1])
        if key[0] == "batch":
            return await self._batch(self._batches.pop((key[1], key[2])))
        return await self._collect(key[1])

    def _apply(self, key: tuple[Any, ...], effect: _Effect) -> None:
        if key[0] == "collect":
            c: Collect = key[1]
            if effect.failure is not None:
                self.sched.collect_failed(c.loop, c.index, effect.failure)
            else:
                self.sched.collected(c.loop, c.index, effect.collected)
            return
        if key[0] == "batch":
            loop, start = key[1], key[2]
            if effect.end is not None:
                self.sched.end(effect.end)
            elif effect.batch is not None:
                self.sched.batch_done(loop, start, effect.batch)
            elif effect.failure is not None:
                self.sched.batch_failed(loop, start, effect.failure)
            return
        inst: Instance = key[1]
        if effect.cel_mode is not None:
            self._cel_modes[inst] = effect.cel_mode
        if effect.loop is not None:
            self.sched.open_loop(
                inst,
                effect.loop.items,
                concurrency=effect.loop.concurrency,
                stop_on_error=effect.loop.stop_on_error,
                batch=effect.loop.batch,
            )
        elif effect.end is not None:
            self.sched.finish(inst, effect.end, effect.output)
        elif effect.failure is not None:
            self.sched.fail(inst, effect.failure)
        else:
            if effect.variables:
                self.vars.update(effect.variables)
            self.sched.succeed(inst, effect.output, effect.ports)

    # --- the budget ------------------------------------------------------------------------------------------------

    def _serve_budget(self) -> None:
        """Take in the children's requests and our parent's answer, then serve what the budget can: grants go to
        children, a filter resumes, a loop opens its next iteration (the scheduler's own), and a shortfall goes to our
        parent."""
        self._dirty = False
        for need in self._mail:
            self.sched.budget.request(need)
        self._mail = []
        for key, granted in self._answers:
            if key == self._ask:
                self._ask = None
                self.sched.budget.answered(granted)
        self._answers = []
        answers, ask = self.sched.answer_budget()
        for a in answers:
            if a.need.requester == LOCAL:
                waiter = self._filters.pop(a.need.key, None)
                if waiter is not None and not waiter.done():
                    waiter.set_result(a.granted)
                else:  # the filter was cancelled meanwhile: give back what it was granted
                    self.sched.budget.used -= a.granted
            else:
                self._signal(a.need.requester, BUDGET, [a.need.key, a.granted])
        if ask is not None and self.parent is not None:
            self._asks += 1
            self._ask = str(self._asks)  # only our parent answers us: a counter names the request
            self._signal(
                self.parent.workflow_id,
                REQUEST_BUDGET,
                [workflow.info().workflow_id, self._ask, ask.need, ask.want, ask.held],
            )

    def _signal(self, workflow_id: str, name: str, args: list[Any]) -> None:
        async def send() -> None:
            try:
                await workflow.get_external_workflow_handle(workflow_id).signal(name, args=args)
            except Exception:  # the child ended meanwhile: nothing reads the answer
                workflow.logger.warning("budget_signal_undelivered", extra={"to": workflow_id, "signal": name})

        self._signals.append(asyncio.create_task(send()))

    async def _take_budget(self, key: str, n: int) -> bool:
        """A filter's items, now or once the budget has them: False at the cap."""
        if self.sched.budget.take(n):
            return True
        waiter: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        self._filters[key] = waiter
        self.sched.budget.request(Need(LOCAL, key, n, n))
        self._dirty = True
        return bool(await waiter)

    # --- the projection -------------------------------------------------------------------------------------------

    def _queue(self, row: StepRow) -> None:
        """Queue a row for the next projection, as storage will write it: `_take_rows` sizes the rows it sends, and a
        character strict UTF-8 can't encode would fail that in workflow code, on every retry. A later row of the same
        attempt replaces it."""
        row = replace(
            row,
            input_preview=storable(row.input_preview),
            output_preview=storable(row.output_preview),
            error_code=sanitize(row.error_code),
            error_message=sanitize(row.error_message),
        )
        self._rows[(row.step_id, row.iteration_key, row.attempt)] = row

    def _take_rows(self) -> list[StepRow]:
        """The next projection's rows, oldest first, within PROJECT_BYTES; one row at least. A backlog (after a
        database outage, say) takes several projections, each well within Temporal's payload limit."""
        taken: list[StepRow] = []
        size = 0
        for key in list(self._rows):
            row_size = len(canonical_json(asdict(self._rows[key])))
            if taken and size + row_size > PROJECT_BYTES:
                break
            taken.append(self._rows.pop(key))
            size += row_size
        return taken

    @staticmethod
    def _preview(value: Any, schema: Mapping[str, Any] | None = None) -> Any:
        """A row's preview: what its schema marks sensitive redacted. The project activity masks the rest against the
        run tree's secret index (engine 2b spec §3.7); the workflow never holds a secret to mask with."""
        return preview(value, schema)

    def _queue_settled(self) -> None:
        """Control steps that settled since the last call. Plugin steps queue their own attempts (`_activity`)."""
        now = workflow.now().isoformat()
        for inst, result in self.sched.take_settled():
            step = self.sched.step(inst)
            if not step.control:
                continue
            error = result.get("error")
            self._queue(
                StepRow(
                    run_id=self.run_id,
                    step_id=str(step.id),
                    node_key=step.key,
                    iteration_key=iteration_key(inst.scope),
                    attempt=1,
                    status="failed" if error else "succeeded",
                    started_at=self._started.get(inst),
                    ended_at=now,
                    output_preview=self._preview(result.get("output")),
                    error_code=error["code"] if error else None,
                    error_message=error["message"] if error else None,
                    cel_mode=self._cel_modes.get(inst),
                )
            )

    async def _project(
        self, rows: list[StepRow], summary: RunSummary | None = None, start: RunStart | None = None
    ) -> None:
        data = ProjectInput(self.tenant_id, rows, summary, start, root_run_id=self.root_run_id)
        await self._send(data)
        await workflow.execute_activity(
            PROJECT,
            data,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_interval=timedelta(seconds=30)),
        )

    async def _shielded(
        self, rows: list[StepRow], summary: RunSummary | None = None, start: RunStart | None = None
    ) -> bool:
        """A write a cancel must not stop: shielded, it's never cancelled, and it lands. True when a cancel arrived
        meanwhile: the caller decides what it means (an end already written stands; a sub-run's first row doesn't)."""
        return await _landed(asyncio.create_task(self._project(rows, summary, start)))

    async def _project_end(self, summary: RunSummary | None) -> bool:
        """The execution's last projections: the rows still queued, in batches, the last one with the run's end, if
        it's given (a batch has none). A cancel that arrives meanwhile comes too late to unmake the end they record:
        each write is shielded, so it's never cancelled, and it lands; the run's result stands, so the projection and
        Temporal agree. True when a cancel arrived meanwhile."""
        self._queue_settled()
        cancelled = False
        while True:
            rows = self._take_rows()
            last = not self._rows
            if rows or (last and summary is not None):
                cancelled = await self._shielded(rows, summary if last else None) or cancelled
            if last:
                break
        return await self._send_signals() or cancelled

    async def _send_signals(self) -> bool:
        """Every budget signal still in flight, sent before the execution ends: a late cancel can't stop them. True
        when a cancel arrived meanwhile."""
        pending, self._signals = self._signals, []
        return await _landed(asyncio.gather(*pending, return_exceptions=True))

    @staticmethod
    def _stored(error: dict[str, Any] | None) -> dict[str, Any] | None:
        """A run's error as storage writes it: the summary and the run's result say the same."""
        if error is None:
            return None
        return {**error, "code": sanitize(error["code"]), "message": sanitize(error["message"])}

    # --- values ----------------------------------------------------------------------------------------------------

    def _view(self, scope: ScopeKey, item: tuple[Any, int] | None = None) -> Any:
        run = {
            "id": self.run_id,
            "started_at": self.run_started_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "now": workflow.now().astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        return resolve.view(self.sched, scope, trigger=self.trigger, variables=dict(self.vars), run=run, item=item)

    async def _values(
        self, owner: Step | None, pairs: list[tuple[str, Any]], scope: ScopeKey
    ) -> tuple[dict[str, Any], str | None]:
        """Every envelope's value, by JSON pointer, and the CEL mode used (activity wins over local)."""
        values: dict[str, Any] = {}
        mode: str | None = None
        v = self._view(scope)
        for pointer, value in pairs:
            if isinstance(value, RefValue):
                values[pointer] = await self._ref(v, value, owner, scope)
                if _decision(owner, pointer) and contains_marker(values[pointer]):
                    values[pointer] = await self._declassified(values[pointer], owner, scope)
                    mode = "activity"
                elif owner is not None and owner.ref == "flow.loop@1" and pointer == "/items":
                    handle = ClaimRef.of(values[pointer])
                    if handle is not None:
                        values[pointer] = await self._items(handle, owner, scope)
                        mode = "activity"
            elif isinstance(value, TemplateValue):
                parts = [await self._part(p, owner, scope) for p in resolve.template_parts(v, value)]
                joined = resolve.join(parts)
                if joined is None:  # a part is a handle: joined where it's resolved (engine 2b spec §4.2)
                    values[pointer] = await self._template(parts, owner, scope)
                    mode = "activity"
                else:
                    values[pointer] = joined
            elif isinstance(value, CelValue):
                record = self.program.record(owner.id if owner is not None else None, pointer)
                task = await self._cel_task(record, [v], owner=owner, scope=scope)
                [outcome] = await self._evaluate(task, owner=owner, scope=scope, decision=_decision(owner, pointer))
                values[pointer] = resolve.outcome_value(outcome)
                mode = "activity" if mode == "activity" or not task.local else "local"
            else:
                values[pointer] = value.value
        return values, mode

    # --- handles (engine 2b spec §3.2–3.3): never read here, resolved in activities ------------------------------

    async def _ref(self, v: Any, value: RefValue, owner: Step | None, scope: ScopeKey) -> Any:
        """A reference: past a handle, the handle to what it addresses. Whether that's missing or null is known only
        where the claim is read, so a reference with a default asks there; so does a pointer past POINTER_MAX."""
        found = resolve.read(v, value.path)
        handle = ClaimRef.of(found)
        if handle is not None and (value.has_default or handle.too_long()):
            found = await self._bounded(handle, owner, scope)
        return resolve.defaulted(found, value)

    async def _part(self, part: str | resolve.Part, owner: Step | None, scope: ScopeKey) -> str | resolve.Part:
        if not isinstance(part, resolve.Part):
            return part
        handle = ClaimRef.of(part.found)
        if handle is None or not handle.too_long():
            return part
        return resolve.Part(await self._bounded(handle, owner, scope), part.default, part.path)

    async def _bounded(self, handle: ClaimRef, owner: Step | None, scope: ScopeKey) -> Any:
        """What `handle` addresses, as the workflow may hold it: a handle within POINTER_MAX (a derived claim's, for a
        longer one), None for null, MISSING for nothing (`claims.derive`)."""
        data = DeriveInput(
            handle.to_json(),
            str(workflow.uuid4()),
            self.root_run_id,
            step_id=str(owner.id) if owner is not None else None,
            iteration_key=iteration_key(scope),
        )
        await self._send(data)
        try:
            derived = await workflow.execute_activity(
                CLAIMS_DERIVE,
                data,
                result_type=DeriveResult,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1)),
            )
        except ActivityError as e:
            if isinstance(e.cause, ActivityCancelled):
                raise asyncio.CancelledError from None
            if isinstance(e.cause, ApplicationError) and e.cause.type == CLAIM_UNAVAILABLE:
                raise resolve.ValueFailure(CLAIM_UNAVAILABLE, CLAIM_REFUSED) from None
            raise resolve.ValueFailure(
                INTERNAL_ERROR, f"A claim couldn't be read ({type(e.cause or e).__name__})."
            ) from None
        if not derived.present:
            return MISSING
        return derived.handle

    async def _template(self, parts: list[str | resolve.Part], owner: Step | None, scope: ScopeKey) -> Any:
        """A template over a handle, joined in `cel.evaluate` once its parts are resolved: claimed when they read
        sensitive data."""
        data = CelInput(
            {},
            claims=self._claiming(owner, scope, tainted=False, decision=False),
            template=[p if isinstance(p, str) else p.to_json() for p in parts],
        )
        return resolve.outcome_value(await self._remote(data))

    async def _declassified(self, handle: Any, owner: Step | None, scope: ScopeKey) -> Any:
        """A decision that reads a handle, made where the claim is read (engine 2b spec §4.2): the value it reveals
        comes back plain, a boolean or the step fails `type_mismatch` (§4.3)."""
        request = EvaluateRequest(self.program.cel_profile, "v", {"v": "bool"}, ({"v": handle},)).to_json()
        data = CelInput(request, claims=self._claiming(owner, scope, tainted=False, decision=True))
        return resolve.outcome_value(await self._remote(data))

    async def _items(self, handle: ClaimRef, owner: Step, scope: ScopeKey) -> list[dict[str, str]]:
        """A loop's items that are a handle (engine 2b spec §4.3): their count, from the activity that reads the claim
        (a listed loop's declassified decision, or the plain count of a list only its size claimed), and each item a
        handle into the list. A count past the largest item cap is cut there: the loop then fails its cap."""
        if handle.extend(str(ITEM_CAP_MAX)).too_long():
            bounded = ClaimRef.of(await self._bounded(handle, owner, scope))
            if bounded is None:
                raise resolve.ValueFailure(cel.TYPE_MISMATCH, "`items` must be a list.")
            handle = bounded
        request = EvaluateRequest(self.program.cel_profile, "size(v)", {"v": "list<dyn>"}, ({"v": handle.to_json()},))
        data = CelInput(request.to_json(), claims=self._claiming(owner, scope, tainted=False, decision=True))
        count = resolve.outcome_value(await self._remote(data))
        return [handle.extend(str(i)).to_json() for i in range(min(int(count), ITEM_CAP_MAX + 1))]

    async def _remote(self, data: CelInput) -> cel.Outcome:
        """One `cel.evaluate` request of one binding set, or a template: its outcome."""
        profile = self.program.cel_profile
        await self._send(data)
        try:
            result = await workflow.execute_activity(
                CEL_EVALUATE,
                data,
                result_type=CelResult,
                task_queue=cel_queue(profile),
                schedule_to_start_timeout=timedelta(seconds=self.cel_schedule_to_start_s),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1)),
            )
        except ActivityError as e:
            if isinstance(e.cause, ActivityCancelled):
                raise asyncio.CancelledError from None
            message = f"No evaluator served `{profile}` ({type(e.cause or e).__name__})."
            raise resolve.ValueFailure(cel.PROFILE_UNAVAILABLE, message) from None
        return cel.Outcome.from_json(result.outcomes[0])

    def _claiming(self, owner: Step | None, scope: ScopeKey, *, tainted: bool, decision: bool) -> Claiming:
        return Claiming(
            root_run_id=self.root_run_id,
            seed=str(workflow.uuid4()),
            tainted=tainted,
            decision=decision,
            step_id=str(owner.id) if owner is not None else None,
            iteration_key=iteration_key(scope),
        )

    async def _cel_task(
        self,
        record: ExpressionRecord,
        views: Sequence[Any],
        *,
        inline: bool = True,
        owner: Step | None = None,
        scope: ScopeKey = (),
    ) -> resolve.CelTask:
        """Bind each view within the workflow task's budget (spec §5.6). Binding converts every value it binds, so
        it's charged as they are (`Measure.nodes`), whether the expression then runs here or in `cel.evaluate`.
        `inline` False: it goes to `cel.evaluate`, whatever its class."""
        bound: list[resolve.Bound] = []
        for v in views:
            await self._yield_point(None)
            b = resolve.bind_view(record, v)
            self._yield.charge(nodes=b.measured.nodes)
            bound.append(await self._bounded_bindings(b, owner, scope))
        local_profile = LOCAL_CEL_PROFILE if inline else None
        return resolve.cel_task(record, bound, local_profile=local_profile, version_profile=self.program.cel_profile)

    async def _bounded_bindings(self, b: resolve.Bound, owner: Step | None, scope: ScopeKey) -> resolve.Bound:
        """A typed path past a handle extends it (`bind`): one past POINTER_MAX derives a claim, as a reference
        does. What it addresses must be there, as a typed path's value must."""
        long = {name: h for name, value in b.bindings.items() if (h := ClaimRef.of(value)) is not None and h.too_long()}
        if not long:
            return b
        bindings = dict(b.bindings)
        for name, handle in long.items():
            bindings[name] = await self._bounded(handle, owner, scope)
            if bindings[name] is MISSING:
                raise resolve.ValueFailure(cel.TYPE_MISMATCH, f"`{name}` is missing")
        return resolve.Bound(bindings, b.measured)

    async def _evaluate(
        self, task: resolve.CelTask, *, owner: Step | None = None, scope: ScopeKey = (), decision: bool = False
    ) -> list[cel.Outcome]:
        """Each binding set's outcome. Sent to `cel.evaluate` with what to do about claims when a binding is a handle,
        or the expression reads sensitive data (engine 2b spec §4.2): resolve them there, and claim the results, or
        give a declassified `decision` back plain."""
        if task.local:
            outcomes = []
            for bindings in task.bindings:  # a filter's items one at a time: each is an evaluation
                await self._yield_point(task.record)
                outcomes.append(task.run_one(bindings))
                self._yield.charge(task.record)
            return outcomes
        out: list[cel.Outcome] = []
        profile = self.program.cel_profile
        claiming = task.record.tainted or any(contains_marker(b) for b in task.bindings)

        def claims() -> Claiming | None:  # a seed per request: its results' claim ids
            return self._claiming(owner, scope, tainted=task.record.tainted, decision=decision) if claiming else None

        envelope = _json_bytes(CelInput(resolve.CelTask(task.record, (), False).request(profile), claims=claims()))
        start, count = 0, len(task.bindings)
        while start < count:
            end, size = resolve.request_end(
                start,
                count,
                lambda i: _json_bytes(task.bindings[i]),
                envelope=envelope,
                batch=CEL_BATCH,
                limit=CEL_REQUEST_BYTES,
            )
            if end == start:
                # This binding set alone would pass Temporal's payload limit: it's never sent (#15). The sets after it
                # can't change the result (a filter fails at its first failing item, and the sets before it were sent
                # already), so they're neither measured nor sent: measuring every oversized set in one workflow task
                # could outlast the SDK's deadlock timeout.
                refused = cel.Outcome(error=cel.INPUT_TOO_LARGE, message=REQUEST_TOO_LARGE)
                return out + [refused] * (count - start)
            chunk = resolve.CelTask(task.record, task.bindings[start:end], False)
            await self._yield_point(None, send=size)
            self._yield.charge(sent=size)
            try:
                result = await workflow.execute_activity(
                    CEL_EVALUATE,
                    CelInput(chunk.request(profile), claims=claims()),
                    result_type=CelResult,
                    task_queue=cel_queue(profile),
                    schedule_to_start_timeout=timedelta(seconds=self.cel_schedule_to_start_s),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1)),
                )
            except ActivityError as e:
                if isinstance(e.cause, ActivityCancelled):  # the run or the scope ended: stop here
                    raise asyncio.CancelledError from None
                message = f"No evaluator served `{profile}` ({type(e.cause or e).__name__})."
                return [cel.Outcome(error=cel.PROFILE_UNAVAILABLE, message=message)] * len(task.bindings)
            out += [cel.Outcome.from_json(o) for o in result.outcomes]
            start = end
        return out

    def _task_budget(self) -> YieldBudget:
        """The current workflow task's budget: it starts afresh when the history length changes, which happens only
        between tasks, in a replay too. The execution's first task gets a tenth of it: that task also starts it."""
        length = workflow.info().get_current_history_length()
        if length != self._yield_task:
            self._yield_task = length
            self._yield.reset(startup=length == self._startup_task)
        return self._yield

    async def _yield_point(self, record: ExpressionRecord | None, *, send: int = 0) -> None:
        """Before binding a view (`record` None) or evaluating `record` locally: when the current workflow task's budget
        is spent, await a 1 ms durable timer, which ends the task (spec §5.6). Concurrent units share the budget and
        one timer, and each checks again once it fires. Before sending a payload (`send` its bytes), the same wait
        keeps a task's commands under Temporal's gRPC message limit (#15, engine 2b spec §5.2)."""
        while True:
            if not self._task_budget().must_yield(record, send=send):
                return
            if self._yield_timer is None or self._yield_timer.done():
                self._yield_timer = asyncio.create_task(asyncio.sleep(0.001))
            await asyncio.shield(self._yield_timer)

    async def _send(self, value: Any) -> None:
        """Before a command carries `value`'s payload: wait for the next workflow task once this one has sent its
        bytes (YIELD_SEND_BYTES), then count them. Every payload the engine sends goes through here — a step's input,
        a request, a projection, a child's start, a continued run's input, the result — and each is at most
        PAYLOAD_BYTES, so a task's completion stays under Temporal's gRPC message limit (engine 2b spec §5.2)."""
        n = encoded_bytes(value, workflow.payload_converter())
        await self._yield_point(None, send=n)
        self._yield.charge(sent=n)

    async def _returned[R](self, result: R) -> R:
        """The execution's result, paced as a command is: it goes out with its workflow task's completion."""
        await self._send(result)
        return result

    def _charge_sent(self, value: Any) -> None:
        """A payload this workflow task records without sending it as a command: a local activity's result."""
        self._task_budget().charge(sent=encoded_bytes(value, workflow.payload_converter()))

    # --- steps -----------------------------------------------------------------------------------------------------

    async def _step(self, inst: Instance) -> _Effect:
        step = self.sched.step(inst)
        skip = ("/collect",) if step.ref == "flow.loop@1" else ("/predicate",) if step.ref == "flow.filter@1" else ()
        pairs = [(p, v) for p, v in step.values if not any(p == s or p.startswith(s + "/") for s in skip)]
        try:
            values, cel_mode = await self._values(step, pairs, inst.scope)
        except resolve.ValueFailure as e:
            if not step.control:  # it never reached an attempt: its one row says why
                self._queue_unstarted(inst, step, e.failure)
            return _Effect(failure=e.failure)
        config = resolve.assemble(step.config, values)
        if not step.control:
            return await self._activity(inst, step, config, cel_mode)
        if step.ref == "flow.filter@1":
            record = self.program.record(step.id, "/predicate")
            if record.tainted or contains_marker(config.get("items")):
                return await self._claimed_filter(inst, step, config.get("items"), record)
        decision = nodes.decide(step.ref, config)
        if decision.failure is not None:
            return _Effect(failure=decision.failure, cel_mode=cel_mode)
        if decision.loop is not None:
            return _Effect(loop=decision.loop, cel_mode=cel_mode)
        if decision.filter_items is not None:
            return await self._filter(inst, step, decision.filter_items)
        if decision.subflow is not None:
            return await self._subflow(inst, step, decision.subflow, cel_mode)
        wake = (
            workflow.now() + timedelta(seconds=decision.wait_s) if decision.wait_s is not None else decision.wait_until
        )
        if wake is not None:
            if cel_mode is not None:
                self._cel_modes[inst] = cel_mode
            return await self._timer(inst, wake)
        return _Effect(
            output=decision.output,
            ports=decision.ports,
            variables=decision.variables,
            end=decision.end,
            cel_mode=cel_mode,
        )

    async def _timer(self, inst: Instance, wake: datetime) -> _Effect:
        """A timer step asleep until `wake`. It isn't outstanding work: a continue-as-new carries its wake time."""
        self._timers[inst] = wake
        await asyncio.sleep(max(0.0, (wake - workflow.now()).total_seconds()))
        del self._timers[inst]
        return _Effect(output={}, cel_mode=self._cel_modes.get(inst))

    async def _filter(self, inst: Instance, step: Step, items: list[Any]) -> _Effect:
        if not await self._take_budget(f"filter:{iteration_key(inst.scope)}:{step.key}", len(items)):
            return _Effect(failure=Failure(ITERATION_CAP_EXCEEDED, CAP_MESSAGE))
        record = self.program.record(step.id, "/predicate")
        views = [self._view(inst.scope, item=(item, i)) for i, item in enumerate(items)]
        try:
            task = await self._cel_task(record, views, inline=len(items) <= FILTER_INLINE)
        except resolve.ValueFailure as e:
            return _Effect(failure=e.failure)
        kept: list[Any] = []
        for item, outcome in zip(items, await self._evaluate(task), strict=True):
            if not outcome.ok:
                return _Effect(failure=Failure(str(outcome.error), outcome.message))
            if not isinstance(outcome.value, bool):
                return _Effect(failure=Failure(cel.TYPE_MISMATCH, "`predicate` must give true or false."))
            if outcome.value:
                kept.append(item)
        return _Effect(output={"items": kept, "count": len(kept)}, cel_mode="local" if task.local else "activity")

    async def _claimed_filter(self, inst: Instance, step: Step, items: Any, record: ExpressionRecord) -> _Effect:
        """A filter over claims, or with a sensitive predicate, run whole in one activity (engine 2b spec §4.4): the
        workflow gets the kept items' handle and the two counts, never a per-item decision, and the budget is charged
        the input count."""
        try:
            base = await self._bounded_bindings(resolve.bind_base(record, self._view(inst.scope)), step, inst.scope)
            request = EvaluateRequest(
                self.program.cel_profile, record.expr, dict(record.declarations), (base.bindings,)
            )
            data = CelInput(
                request.to_json(),
                claims=self._claiming(step, inst.scope, tainted=record.tainted, decision=False),
                filter={"items": items, "record": record.to_json()},
            )
            outcome = await self._remote(data)
        except resolve.ValueFailure as e:
            return _Effect(failure=e.failure)
        if not outcome.ok:
            return _Effect(failure=Failure(str(outcome.error), outcome.message))
        result = outcome.value
        if not await self._take_budget(f"filter:{iteration_key(inst.scope)}:{step.key}", int(result["input"])):
            return _Effect(failure=Failure(ITERATION_CAP_EXCEEDED, CAP_MESSAGE))
        return _Effect(output={"items": result["items"], "count": result["count"]}, cel_mode="activity")

    async def _collect(self, c: Collect) -> _Effect:
        step = self.sched.step(c.loop)
        collect = step.config.get("collect")
        pairs = [(p, v) for p, v in step.values if p == "/collect" or p.startswith("/collect/")]
        try:
            values, _ = await self._values(step, pairs, c.scope)
        except resolve.ValueFailure as e:
            return _Effect(failure=e.failure)
        if collect is None:
            return _Effect(collected=None)
        return _Effect(collected=resolve.assemble({"collect": collect}, values)["collect"])

    # --- children -------------------------------------------------------------------------------------------------

    async def _subflow(self, inst: Instance, step: Step, start: nodes.SubflowStart, cel_mode: str | None) -> _Effect:
        """A `run_workflow` step: its pinned version runs as a child `RunGraph`, a run of its own that shares the
        deadline and draws on this execution's budget. Its outputs are the step's output; its failure, the step's."""
        version = self.program.subflows.get(str(step.id))
        if version is None or self.depth >= MAX_DEPTH:
            reason = "no pinned version" if version is None else f"more than {MAX_DEPTH} sub-flows deep"
            return _Effect(failure=Failure(VERSION_UNUSABLE, f"`{step.key}` can't run its sub-flow: {reason}."))
        child_run = str(workflow.uuid4())
        child = run_workflow_id(self.tenant_id, child_run)  # its workflow id, and its key in this budget
        trigger = await self._hand_over(child_run, version, start.input)
        if isinstance(trigger, Failure):
            return _Effect(failure=trigger, cel_mode=cel_mode)
        grant = self.sched.budget.start_child(child, SUBFLOW_GRANT)
        parent = Parent(
            workflow_id=workflow.info().workflow_id,
            run_id=self.run_id,
            step_id=str(step.id),
            iteration_key=iteration_key(inst.scope),
            kind=SUBFLOW,
            deadline=self.deadline.isoformat(),
            grant=grant,
            depth=self.depth + 1,
            root_run_id=self.root_run_id,
        )
        run = RunInput(
            self.tenant_id,
            child_run,
            version,
            trigger,
            self.mode,
            self.max_run_duration_s,
            self.cel_schedule_to_start_s,
            parent=parent,
            workflow_id=start.workflow_id,
            checkpoint_events=self.checkpoint_events,
            drain_events=self.drain_events,
        )
        if not fits(run, workflow.payload_converter()):  # engine 2b spec §5.2: never sent, so it never ran
            self.sched.budget.settle_child(child, 0)
            self._dirty = True
            return _Effect(failure=Failure(PAYLOAD_TOO_LARGE, SUBFLOW_INPUT_TOO_LARGE), cel_mode=cel_mode)
        used: int | None = None  # until it reports, all it was granted counts: it may have run
        started = workflow.now().isoformat()
        try:
            try:
                await self._send(run)
            except asyncio.CancelledError:  # cancelled before it was sent: it never ran
                used = 0
                raise
            try:
                handle = await workflow.start_child_workflow(
                    "RunGraph", run, result_type=RunResult, **child_options(child)
                )
            except ChildWorkflowError:  # cancelled before its start went out, as the SDK reports it: it never ran
                used = 0
                raise asyncio.CancelledError from None
            result = await handle
            used = result.iterations
        except ChildWorkflowError as e:  # it failed as a workflow, which a run never does: a bug, or terminated
            failure = self._lost("sub-flow", e)
            await self._lost_end(run, started, failure)
            return _Effect(failure=failure, cel_mode=cel_mode)
        finally:
            self.sched.budget.settle_child(child, used)
            self._dirty = True
        if result.status == "succeeded":
            return _Effect(output=dict(result.outputs or {}), cel_mode=cel_mode)
        error = result.error or {"code": result.status, "message": f"The sub-flow ended {result.status}."}
        return _Effect(failure=Failure(str(error["code"]), str(error["message"])), cel_mode=cel_mode)

    async def _crossing[R](self, name: str, data: Any, result_type: type[R]) -> R | Failure:
        """An activity that hands claims to another run (engine 2b spec §3.4): its result, or why it failed."""
        await self._send(data)
        try:
            result: R = await workflow.execute_activity(
                name,
                data,
                result_type=result_type,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1)),
            )
            return result
        except ActivityError as e:
            if isinstance(e.cause, ActivityCancelled):
                raise asyncio.CancelledError from None
            if isinstance(e.cause, ApplicationError) and e.cause.type == CLAIM_UNAVAILABLE:
                return Failure(CLAIM_UNAVAILABLE, CLAIM_REFUSED)
            return Failure(INTERNAL_ERROR, f"Claims couldn't cross to another run ({type(e.cause or e).__name__}).")

    async def _hand_over(self, child_run: str, version: str, value: dict[str, Any]) -> dict[str, Any] | Failure:
        """A sub-flow's input, split for the child as a trigger is, this run's handles in it granted to the child
        (engine 2b spec §3.4, §3.5): the envelope its start carries."""
        found = await self._crossing(
            CLAIMS_CHILD_INPUT, ChildInput(child_run, version, value, self.root_run_id), ChildInputResult
        )
        if isinstance(found, Failure):
            return found
        if found.trigger is None:
            return Failure(INPUT_INVALID, " ".join(found.reasons))
        return found.trigger

    async def _grant(self, to: str, value: Any) -> Failure | None:
        """The handles in `value`, and the claims they nest, granted to run `to` (engine 2b spec §3.4)."""
        found = await self._crossing(CLAIMS_GRANT, GrantInput(to, value, self.root_run_id), type(None))
        return found if isinstance(found, Failure) else None

    @staticmethod
    def _lost(kind: str, e: ChildWorkflowError) -> Failure:
        """A child that ended without a result: terminated from outside Dewpoint, or failed as a workflow (a bug)."""
        if isinstance(e.cause, TerminatedError):
            return Failure(TERMINATED, f"The {kind} was terminated outside Dewpoint.")
        return Failure(INTERNAL_ERROR, f"The {kind} ended without a result ({type(e.cause).__name__}).")

    async def _lost_end(self, run: RunInput, started_at: str, failure: Failure) -> None:
        """A sub-run that ended without a result never wrote its end: its row would stay `running`, holding its
        references (spec §4.5). Its parent writes it, unless it has one, with its whole grant as counted here: its
        first grant and every one it asked for since, which the parent debits as it settles the child. It writes the
        row too, in case the child was ended before its own: a start written later changes nothing."""
        whole = self.sched.budget.reserved.get(run_workflow_id(run.tenant_id, run.run_id), 0)  # before it's settled
        end = RunSummary(run.run_id, "failed", workflow.now().isoformat(), failure.code, failure.message, whole, True)
        await self._shielded([], end, RunStart.of(run, started_at))

    def _outer(self, loop: Instance) -> list[dict[str, Any]]:
        """The loop's enclosing scopes as its batch reads them, outermost first: the results its body can
        reference, and each enclosing loop's item."""
        reads = self.program.outer_reads(loop.step)
        out = []
        for depth in range(len(loop.scope) + 1):
            scope = self.sched.scopes[loop.scope[:depth]]
            results = {k: v for k, v in scope.results.items() if reads is None or k in reads}
            out.append(
                {"key": [[k, i] for k, i in scope.key], "results": results, "item": scope.item, "index": scope.index}
            )
        return out

    async def _batch(self, b: Batch) -> _Effect:
        """A batch of a loop's items, as a child `LoopBatch`. It writes its iterations' rows into this run, and
        returns what they collected."""
        step = self.sched.step(b.loop)
        # from the input, not the workflow id: a replay of this history sees the same id (the run id names the logical
        # run, the loop step and its scope name the loop, the start names the batch)
        child = batch_workflow_id(self.tenant_id, self.run_id, str(step.id), iteration_key(b.loop.scope), b.start)
        converter = workflow.payload_converter()
        draft = self._batch_input(b, len(b.items))
        if not fits(draft, converter):  # engine 2b spec §5.2: as many of its items as fit, in order; the rest follow
            items = b.items
            envelope = encoded_bytes(replace(draft, items=[]), converter)
            fit, _ = resolve.request_end(
                0,
                len(items),
                lambda i: len(converter.to_payloads([items[i]])[0].data),
                envelope=envelope,
                batch=len(items),
                limit=payload_bytes(),
            )
            if fit == 0:  # its first item alone doesn't fit: the loop fails there, and nothing is dropped
                return _Effect(failure=Failure(PAYLOAD_TOO_LARGE, BATCH_ITEM_TOO_LARGE))
            self.sched.cut_batch(b.loop, b.start, b.start + fit)
            b = replace(b, items=items[:fit])
        grant = self.sched.budget.start_child(child, len(b.items))
        batch = self._batch_input(b, grant)
        used: int | None = None  # until it reports, all it was granted counts: it may have run
        try:
            try:
                await self._send(batch)
            except asyncio.CancelledError:  # cancelled before it was sent: it never ran
                used = 0
                raise
            try:
                handle = await workflow.start_child_workflow(
                    "LoopBatch", batch, result_type=BatchResult, **child_options(child)
                )
            except ChildWorkflowError:  # cancelled before its start went out, as the SDK reports it: it never ran
                used = 0
                raise asyncio.CancelledError from None
            result = await handle
            used = result.iterations
        except ChildWorkflowError as e:  # its version didn't load or compile, a bug, or it was terminated
            cause = e.cause
            if isinstance(cause, ApplicationError) and cause.type in (VERSION_UNUSABLE, INTERNAL_ERROR):
                return _Effect(failure=Failure(cause.type, cause.message))
            return _Effect(failure=self._lost("batch", e))
        finally:
            self.sched.budget.settle_child(child, used)
            self._dirty = True
        if result.end is not None:
            end = RunEnd.from_json(result.end)
            if end.status == "cancelled":
                return _Effect(failure=CANCELLED)
            return _Effect(end=end)
        stopped = Failure.from_json(result.stopped) if result.stopped else None
        return _Effect(batch=BatchOutcome(list(result.collected), list(result.failures), stopped))

    def _batch_input(self, b: Batch, grant: int) -> BatchInput:
        step = self.sched.step(b.loop)
        loop = self.sched.loops[b.loop]
        parent = Parent(
            workflow_id=workflow.info().workflow_id,
            run_id=self.run_id,
            step_id=str(step.id),
            iteration_key=iteration_key(b.loop.scope),
            kind=BATCH,
            deadline=self.deadline.isoformat(),
            grant=grant,
            depth=self.depth,
            root_run_id=self.root_run_id,
        )
        return BatchInput(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            version_id=self.version_id,
            loop_step=str(step.id),
            outer=self._outer(b.loop),
            items=b.items,
            offset=b.start,
            concurrency=loop.concurrency,
            stop_on_error=loop.stop_on_error,
            trigger=self.trigger,
            variables=dict(self.vars),
            run_started_at=self.run_started_at.isoformat(),
            parent=parent,
            mode=self.mode,
            cel_schedule_to_start_s=self.cel_schedule_to_start_s,
            checkpoint_events=self.checkpoint_events,
            drain_events=self.drain_events,
        )

    # --- plugin steps ---------------------------------------------------------------------------------------------

    async def _activity(self, inst: Instance, step: Step, config: Any, cel_mode: str | None) -> _Effect:
        """A plugin step, one activity execution per attempt (`maximum_attempts=1`). The workflow decides each retry,
        so a timeout after an ambiguous send is never repeated, and projects each attempt's rows, so no row write can
        repeat an effect (decisions 7, 12)."""
        manifest = self.program.manifests[step.ref]
        retry = manifest["retry"]
        attempts = step.max_attempts or int(retry["max_attempts"])
        timeout = timedelta(seconds=step.timeout_s or float(manifest["timeout_s"]))
        ambiguous = manifest["side_effect"] == AMBIGUOUS
        attempt = 1
        while True:
            row = StepRow(
                run_id=self.run_id,
                step_id=str(step.id),
                node_key=step.key,
                iteration_key=iteration_key(inst.scope),
                attempt=attempt,
                status="running",
                started_at=workflow.now().isoformat(),
                input_preview=self._preview(config, manifest["config_schema"]),
                cel_mode=cel_mode,
            )
            self._queue(row)
            sent = StepInput(
                tenant_id=self.tenant_id,
                run_id=self.run_id,
                step_id=str(step.id),
                node_key=step.key,
                iteration_key=iteration_key(inst.scope),
                ref=step.ref,
                config=config,
                mode=self.mode,
                attempt=attempt,
                root_run_id=self.root_run_id,
            )
            if not fits(sent, workflow.payload_converter()):  # engine 2b spec §5.2: never sent, so it never ran
                failure = Failure(PAYLOAD_TOO_LARGE, STEP_INPUT_TOO_LARGE, attempt)
                ended = workflow.now().isoformat()
                self._queue(
                    replace(
                        row, status="failed", ended_at=ended, error_code=failure.code, error_message=failure.message
                    )
                )
                return _Effect(failure=failure, cel_mode=cel_mode)
            try:
                await self._send(sent)
            except asyncio.CancelledError:  # the run or the scope ended before it was sent: nothing ran
                self._queue(replace(row, status="cancelled", ended_at=workflow.now().isoformat()))
                raise
            try:
                result = await workflow.execute_activity(
                    step_activity(step.ref),
                    sent,
                    result_type=StepResult,
                    start_to_close_timeout=timeout,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            except (asyncio.CancelledError, ActivityError) as e:
                if isinstance(e, ActivityError) and not isinstance(e.cause, ActivityCancelled):
                    failure, outcome, retryable = self._failed_attempt(e, row, step.key, ambiguous, retry)
                    if not retryable or attempt >= attempts:
                        return _Effect(failure=failure, cel_mode=cel_mode)
                    await asyncio.sleep(_backoff(retry, attempt))  # a durable timer
                    attempt += 1
                    continue
                # The run or the scope ended: the SDK reports our own cancel as an ActivityError. Never retry it.
                outcome = OUTCOME_UNKNOWN if ambiguous else None  # its request may have been sent
                self._queue(replace(row, status="cancelled", ended_at=workflow.now().isoformat(), outcome=outcome))
                raise asyncio.CancelledError from None
            if tainted_positions(result.output, self._output_shape(step.ref)):  # the tripwire (engine 2b spec §3.6)
                raise ExposedError(f"`{step.ref}` returned plain data at a sensitive position.")
            self._queue(
                replace(
                    row,
                    status="succeeded",
                    ended_at=workflow.now().isoformat(),
                    output_preview=self._preview(result.output, manifest["output_schema"]),
                    outcome=result.outcome,
                )
            )
            return _Effect(output=result.output, cel_mode=cel_mode)

    def _output_shape(self, ref: str) -> Shape:
        """The taint of a node type's output, from its manifest (engine 2b spec §4.1): what must arrive claimed."""
        shape = self._shapes.get(ref)
        if shape is None:
            shape = self._shapes[ref] = from_schema(self.program.manifests[ref]["output_schema"])
        return shape

    def _queue_unstarted(self, inst: Instance, step: Step, failure: Failure) -> None:
        now = workflow.now().isoformat()
        self._queue(
            StepRow(
                run_id=self.run_id,
                step_id=str(step.id),
                node_key=step.key,
                iteration_key=iteration_key(inst.scope),
                attempt=1,
                status="failed",
                started_at=self._started.get(inst, now),
                ended_at=now,
                error_code=failure.code,
                error_message=failure.message,
            )
        )

    def _failed_attempt(
        self, e: ActivityError, row: StepRow, key: str, ambiguous: bool, retry: Mapping[str, Any]
    ) -> tuple[Failure, str | None, bool]:
        failure, outcome, retryable = _attempt_failed(
            e, key, row.attempt, ambiguous=ambiguous, non_retryable=retry["non_retryable"]
        )
        self._queue(
            replace(
                row,
                status="failed",
                ended_at=workflow.now().isoformat(),
                error_code=failure.code,
                error_message=failure.message,
                outcome=outcome,
            )
        )
        return failure, outcome, retryable

    # --- continue-as-new ------------------------------------------------------------------------------------------

    def _snapshot(self) -> dict[str, Any]:
        """Where a continued run carries on (spec §6, `snapshot_format` 1). The projection is written first, so no
        row is carried; timers carry their wake times."""
        return {
            "snapshot_format": SNAPSHOT_FORMAT,
            "scheduler": self.sched.to_json(),
            "variables": self.vars,
            "run_started_at": self.run_started_at.isoformat(),
            "deadline": self.deadline.isoformat(),
            "drained": self._drained,
            "timers": [
                [
                    [[k, n] for k, n in i.scope],
                    str(i.step),
                    wake.isoformat(),
                    self._started.get(i),
                    self._cel_modes.get(i),
                ]
                for i, wake in self._timers.items()
            ],
        }

    def _restore(self, program: Program, snapshot: dict[str, Any]) -> None:
        if snapshot.get("snapshot_format") != SNAPSHOT_FORMAT:
            raise ValueError(f"unknown snapshot format {snapshot.get('snapshot_format')!r}")
        self.program = program
        self.sched = Scheduler.from_json(program, snapshot["scheduler"])
        self.vars = dict(snapshot["variables"])
        for key, step, wake, started, mode in snapshot["timers"]:
            inst = Instance(tuple((str(k), int(n)) for k, n in key), uuid.UUID(step))
            self._timers[inst] = datetime.fromisoformat(wake)
            if started:
                self._started[inst] = started
            if mode:
                self._cel_modes[inst] = mode
            self._resume.append(inst)

    async def _flush(self) -> None:
        """Before continuing as new: every queued row written, and every signal sent. A cancel that arrived meanwhile
        ends the execution instead (raised once they have landed): a continued run wouldn't inherit it."""
        if await self._project_end(None):
            raise asyncio.CancelledError


__all__ = [
    "CEL_BATCH",
    "CEL_REQUEST_BYTES",
    "CONTINUE",
    "DEADLINE_EXCEEDED",
    "INTERNAL_ERROR",
    "IN_FLIGHT_CAP",
    "MAX_DEPTH",
    "NODE_TYPE_UNAVAILABLE",
    "PROJECT_BYTES",
    "SUBFLOW_GRANT",
    "VERSION_UNUSABLE",
    "Execution",
    "child_options",
]
