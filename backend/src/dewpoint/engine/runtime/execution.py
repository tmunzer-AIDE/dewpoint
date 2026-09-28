# SPDX-License-Identifier: Apache-2.0
"""What every execution of a graph shares (spec §6): a run, a sub-flow and a failure handler (`RunGraph`), and a loop
batch (`LoopBatch`). Each drives its scheduler until it ends: every ready step runs as one future (its values
resolved, then a control node decides, a plugin step runs as its activity, a sub-flow or a batch runs as a child).
At most IN_FLIGHT_CAP futures are outstanding, plus one projection; completions are applied in (scope, topological)
order, so a replay applies them the same way. Nothing else creates concurrency.

Children draw their iterations from their parent's budget (spec §6): a child signals `request_budget` to its parent,
which answers `budget` in the order the requests reach its history."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError, TimeoutError
from temporalio.exceptions import CancelledError as ActivityCancelled

with workflow.unsafe.imports_passed_through():
    from dewpoint.engine.canonical import canonical_json
    from dewpoint.engine.cel import evaluate as cel
    from dewpoint.engine.cel.profile import LOCAL_CEL_PROFILE
    from dewpoint.engine.cel.route import YieldBudget
    from dewpoint.engine.graph.values import CelValue, RefValue, TemplateValue
    from dewpoint.engine.runtime import nodes, resolve
    from dewpoint.engine.runtime.activities import (
        BATCH,
        BUDGET,
        CEL_EVALUATE,
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
    from dewpoint.engine.runtime.program import Program, Step
    from dewpoint.engine.runtime.projection import (
        Secrets,
        mask,
        preview,
        remember,
        sanitize,
        sensitive_values,
        storable,
    )
    from dewpoint.engine.runtime.scheduler import (
        CAP_MESSAGE,
        ITERATION_CAP_EXCEEDED,
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

IN_FLIGHT_CAP = 100  # activities and child workflows outstanding per execution (spec §6)
PROJECT_BYTES = 256 * 1024  # a projection's rows at most, as JSON: far below Temporal's 2 MiB payload limit
CEL_BATCH = 1_000  # binding sets per cel.evaluate request
SUBFLOW_GRANT = 1_000  # a sub-flow's initial grant (spec §6)
MAX_DEPTH = 5  # sub-flows nest at most this deep (spec §6; publish checks it too)
DEADLINE_EXCEEDED = "deadline_exceeded"
VERSION_UNUSABLE = "version_unusable"  # this build can't load or compile the version
INTERNAL_ERROR = "internal_error"  # an exception in workflow code: a bug
NODE_TYPE_UNAVAILABLE = "node_type_unavailable"  # the registry has it, but this build's workers don't run it
CANCELLED = Failure("cancelled", "The run was cancelled.")
AMBIGUOUS = "ambiguous"  # a manifest's side_effect: the request may have been sent


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


class Execution:
    """The drive loop and everything it runs. A subclass sets the context (`_context`) and a scheduler, then drives."""

    program: Program
    sched: Scheduler

    def __init__(self) -> None:
        self._yield = YieldBudget()
        self._rows: dict[tuple[str, str, int], StepRow] = {}  # queued for the next projection, per attempt
        self._secrets: Secrets = ()  # sensitive values seen so far: masked in everything projected
        self._started: dict[Instance, str] = {}
        self._cel_modes: dict[Instance, str] = {}
        self._projects = 0
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
    ) -> None:
        self.tenant_id, self.run_id, self.version_id, self.mode = tenant_id, run_id, version_id, mode
        self.trigger = trigger
        self.cel_schedule_to_start_s = cel_schedule_to_start_s
        self.max_run_duration_s = max_run_duration_s
        self.parent = parent
        self.depth = parent.depth if parent is not None else 0
        self.run_started_at, self.deadline = run_started_at, deadline
        self.vars: dict[str, Any] = {}
        if parent is not None:
            self._secrets = remember((), tuple(parent.secrets))

    # --- the scheduler loop ----------------------------------------------------------------------------------------

    async def _drive(self) -> None:
        """Drive the scheduler until the execution ends."""
        tasks: dict[tuple[Any, ...], asyncio.Task[_Effect | None]] = {}
        waiting: list[tuple[Any, ...]] = []
        clock = asyncio.create_task(asyncio.sleep(max(0.0, (self.deadline - workflow.now()).total_seconds())))
        try:
            while self.sched.ended is None:
                self._serve_budget()
                waiting += [("step", i) for i in self.sched.take_ready()]
                waiting += [("collect", c) for c in self.sched.take_collects()]
                for b in self.sched.take_batches():
                    self._batches[(b.loop, b.start)] = b
                    waiting.append(("batch", b.loop, b.start))
                for inst in self.sched.take_cancels():
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
                while waiting and self._in_flight(tasks) < IN_FLIGHT_CAP:
                    unit = waiting.pop(0)
                    tasks[unit] = asyncio.create_task(self._unit(unit))
                if self._rows and not any(key[0] == "project" for key in tasks):  # one at a time: rows wait for it
                    self._projects += 1
                    tasks[("project", self._projects)] = asyncio.create_task(self._project(self._take_rows()))
                if not tasks and self._ask is None:  # waiting for our parent's answer isn't stuck: nothing else is
                    raise RuntimeError("nothing is running and the run hasn't ended")
                wake = asyncio.create_task(
                    workflow.wait_condition(lambda: bool(self._mail or self._answers or self._dirty))
                )
                done, _ = await workflow.wait([*tasks.values(), clock, wake], return_when=asyncio.FIRST_COMPLETED)
                wake.cancel()
                self._yield.reset()
                if clock in done:
                    self.sched.end(
                        RunEnd(DEADLINE_EXCEEDED, Failure(DEADLINE_EXCEEDED, "The run passed its deadline."))
                    )
                    break
                for key in sorted((k for k, t in tasks.items() if t in done), key=self._rank):
                    effect = tasks.pop(key).result()
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

    def _learn(self, value: Any, schema: Mapping[str, Any] | None) -> None:
        self._secrets = remember(self._secrets, sensitive_values(value, schema))

    def _preview(self, value: Any, schema: Mapping[str, Any] | None = None) -> Any:
        return preview(value, schema, self._secrets)

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
                    error_message=mask(error["message"], self._secrets) if error else None,
                    cel_mode=self._cel_modes.get(inst),
                )
            )

    async def _project(
        self, rows: list[StepRow], summary: RunSummary | None = None, start: RunStart | None = None
    ) -> None:
        await workflow.execute_activity(
            PROJECT,
            ProjectInput(self.tenant_id, rows, summary, start),
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
                values[pointer] = resolve.ref(v, value)
            elif isinstance(value, TemplateValue):
                values[pointer] = resolve.template(v, value)
            elif isinstance(value, CelValue):
                record = self.program.record(owner.id if owner is not None else None, pointer)
                task = resolve.cel_task(
                    record, [v], local_profile=LOCAL_CEL_PROFILE, version_profile=self.program.cel_profile
                )
                [outcome] = await self._evaluate(task)
                values[pointer] = resolve.outcome_value(outcome)
                mode = "activity" if mode == "activity" or not task.local else "local"
            else:
                values[pointer] = value.value
        return values, mode

    async def _evaluate(self, task: resolve.CelTask) -> list[cel.Outcome]:
        if task.local:
            if self._yield.must_yield(task.record):
                await asyncio.sleep(0.001)  # a durable timer: the workflow task ends here (spec §5.6)
                self._yield.reset()
            outcomes = task.run_local()
            for _ in outcomes:
                self._yield.charge(task.record)
            return outcomes
        out: list[cel.Outcome] = []
        profile = self.program.cel_profile
        for i in range(0, len(task.bindings), CEL_BATCH):
            chunk = resolve.CelTask(task.record, task.bindings[i : i + CEL_BATCH], False)
            try:
                result = await workflow.execute_activity(
                    CEL_EVALUATE,
                    CelInput(chunk.request(profile)),
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
        return out

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
        decision = nodes.decide(step.ref, config)
        if decision.failure is not None:
            return _Effect(failure=decision.failure, cel_mode=cel_mode)
        if decision.loop is not None:
            return _Effect(loop=decision.loop, cel_mode=cel_mode)
        if decision.filter_items is not None:
            return await self._filter(inst, step, decision.filter_items)
        if decision.subflow is not None:
            return await self._subflow(inst, step, decision.subflow, cel_mode)
        if decision.wait_s is not None:
            await asyncio.sleep(decision.wait_s)
        if decision.wait_until is not None:
            await asyncio.sleep(max(0.0, (decision.wait_until - workflow.now()).total_seconds()))
        return _Effect(
            output=decision.output,
            ports=decision.ports,
            variables=decision.variables,
            end=decision.end,
            cel_mode=cel_mode,
        )

    async def _filter(self, inst: Instance, step: Step, items: list[Any]) -> _Effect:
        if not await self._take_budget(f"filter:{iteration_key(inst.scope)}:{step.key}", len(items)):
            return _Effect(failure=Failure(ITERATION_CAP_EXCEEDED, CAP_MESSAGE))
        record = self.program.record(step.id, "/predicate")
        views = [self._view(inst.scope, item=(item, i)) for i, item in enumerate(items)]
        try:
            task = resolve.cel_task(
                record, views, local_profile=LOCAL_CEL_PROFILE, version_profile=self.program.cel_profile
            )
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
        child = str(workflow.uuid4())
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
            secrets=list(self._secrets),
        )
        run = RunInput(
            self.tenant_id,
            child,
            version,
            start.input,
            self.mode,
            self.max_run_duration_s,
            self.cel_schedule_to_start_s,
            parent=parent,
            workflow_id=start.workflow_id,
        )
        used: int | None = None
        try:
            result = await workflow.execute_child_workflow(
                "RunGraph", run, result_type=RunResult, **child_options(child)
            )
            used = result.iterations
        except ChildWorkflowError as e:  # it failed as a workflow, which a run never does: a bug, or terminated
            message = f"The sub-flow ended without a result ({type(e.cause).__name__})."
            return _Effect(failure=Failure(INTERNAL_ERROR, message), cel_mode=cel_mode)
        finally:
            self.sched.budget.settle_child(child, used)
            self._dirty = True
        self._secrets = remember(self._secrets, tuple(result.secrets))
        if result.status == "succeeded":
            return _Effect(output=dict(result.outputs or {}), cel_mode=cel_mode)
        error = result.error or {"code": result.status, "message": f"The sub-flow ended {result.status}."}
        return _Effect(failure=Failure(str(error["code"]), str(error["message"])), cel_mode=cel_mode)

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
        loop = self.sched.loops[b.loop]
        # from the input, not the workflow id: a replay of this history sees the same id (the run id names the logical
        # run, the loop step and its scope name the loop, the start names the batch)
        child = f"{self.run_id}/{step.id}/{iteration_key(b.loop.scope)}/batch:{b.start}"
        grant = self.sched.budget.start_child(child, len(b.items))
        parent = Parent(
            workflow_id=workflow.info().workflow_id,
            run_id=self.run_id,
            step_id=str(step.id),
            iteration_key=iteration_key(b.loop.scope),
            kind=BATCH,
            deadline=self.deadline.isoformat(),
            grant=grant,
            depth=self.depth,
            secrets=list(self._secrets),
        )
        batch = BatchInput(
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
        )
        used: int | None = None
        try:
            result = await workflow.execute_child_workflow(
                "LoopBatch", batch, result_type=BatchResult, **child_options(child)
            )
            used = result.iterations
        except ChildWorkflowError as e:  # its version didn't load or compile, a bug, or it was terminated
            cause = e.cause
            if isinstance(cause, ApplicationError) and cause.type in (VERSION_UNUSABLE, INTERNAL_ERROR):
                return _Effect(failure=Failure(cause.type, cause.message))
            return _Effect(failure=Failure(INTERNAL_ERROR, "The batch ended without a result."))
        finally:
            self.sched.budget.settle_child(child, used)
            self._dirty = True
        self._secrets = remember(self._secrets, tuple(result.secrets))
        if result.end is not None:
            end = RunEnd.from_json(result.end)
            if end.status == "cancelled":
                return _Effect(failure=CANCELLED)
            return _Effect(end=end)
        stopped = Failure.from_json(result.stopped) if result.stopped else None
        return _Effect(batch=BatchOutcome(list(result.collected), list(result.failures), stopped))

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
        self._learn(config, manifest["config_schema"])  # a resolved sensitive value, before anything can echo it
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
            try:
                result = await workflow.execute_activity(
                    step_activity(step.ref),
                    StepInput(
                        tenant_id=self.tenant_id,
                        run_id=self.run_id,
                        step_id=str(step.id),
                        node_key=step.key,
                        iteration_key=iteration_key(inst.scope),
                        ref=step.ref,
                        config=config,
                        mode=self.mode,
                        attempt=attempt,
                    ),
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
                self._queue(replace(row, status="cancelled", ended_at=workflow.now().isoformat()))
                raise asyncio.CancelledError from None
            self._learn(result.output, manifest["output_schema"])
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
                error_message=mask(failure.message, self._secrets),
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
                error_message=mask(failure.message, self._secrets),
                outcome=outcome,
            )
        )
        return failure, outcome, retryable


__all__ = [
    "CEL_BATCH",
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
