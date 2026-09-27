# SPDX-License-Identifier: Apache-2.0
"""`RunGraph` (spec §6): loads the pinned version, then drives the scheduler until the run ends. Each ready step runs
as one future: its values are resolved (CEL inline or through `cel.evaluate`), then a control node decides in the
workflow, or a plugin step runs as its activity. At most IN_FLIGHT_CAP futures are outstanding, plus one projection;
completions are applied in (scope, topological) order, so a replay applies them the same way. Nothing else creates
concurrency."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, TimeoutError
from temporalio.exceptions import CancelledError as ActivityCancelled

with workflow.unsafe.imports_passed_through():
    from dewpoint.engine.cel import evaluate as cel
    from dewpoint.engine.cel.profile import LOCAL_CEL_PROFILE
    from dewpoint.engine.cel.route import YieldBudget
    from dewpoint.engine.graph.values import CelValue, RefValue, TemplateValue, iter_values, pointer_str
    from dewpoint.engine.runtime import nodes, resolve
    from dewpoint.engine.runtime.activities import (
        CEL_EVALUATE,
        LOAD_VERSION,
        OUTCOME_UNKNOWN,
        PROJECT,
        CelInput,
        CelResult,
        LoadVersionInput,
        ProjectInput,
        RunInput,
        RunResult,
        RunSummary,
        StepInput,
        StepResult,
        StepRow,
        VersionData,
        cel_queue,
        step_activity,
    )
    from dewpoint.engine.runtime.program import Step, compile_program
    from dewpoint.engine.runtime.projection import Secrets, mask, preview, remember, sensitive_values
    from dewpoint.engine.runtime.scheduler import (
        ITERATION_CAP_EXCEEDED,
        Collect,
        Failure,
        Instance,
        RunEnd,
        Scheduler,
        ScopeKey,
        iteration_key,
    )

IN_FLIGHT_CAP = 100  # activities and child workflows outstanding per execution (spec §6)
CEL_BATCH = 1_000  # binding sets per cel.evaluate request
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


def _attempt_failed(
    error: ActivityError, key: str, attempt: int, *, ambiguous: bool, non_retryable: Sequence[str]
) -> tuple[Failure, str | None, bool]:
    """How one attempt failed: (the failure, its outcome, whether another attempt may follow)."""
    cause = error.cause
    if isinstance(cause, ApplicationError) and cause.type == "NotFoundError":  # the SDK: no such activity here
        return Failure(NODE_TYPE_UNAVAILABLE, f"No worker of this build runs `{key}`'s node type.", attempt), None, True
    if isinstance(cause, ApplicationError):  # the node's own error, mapped by the activity
        details = cause.details[0] if cause.details and isinstance(cause.details[0], dict) else {}
        code = cause.type or "error"
        retryable = not cause.non_retryable and code not in non_retryable
        return Failure(code, cause.message, attempt), details.get("outcome"), retryable
    # A timeout or a lost worker: the node may have done its work, and it never saw the error to map it.
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


def _backoff(retry: Mapping[str, Any], attempt: int) -> float:
    """Seconds before attempt `attempt + 1`, from the manifest's retry settings."""
    delay = float(retry["initial_interval_s"]) * float(retry["backoff"]) ** (attempt - 1)
    return min(delay, float(retry["max_interval_s"]))


@workflow.defn(name="RunGraph")
class RunGraph:
    def __init__(self) -> None:
        self._budget = YieldBudget()
        self._rows: dict[tuple[str, str, int], StepRow] = {}  # queued for the next projection, per attempt
        self._secrets: Secrets = ()  # sensitive values seen so far: masked in everything projected
        self._started: dict[Instance, str] = {}
        self._cel_modes: dict[Instance, str] = {}
        self._projects = 0

    @workflow.run
    async def run(self, start: RunInput) -> RunResult:
        """Every way a run ends is projected. Python exceptions in workflow code would fail the workflow task, which
        Temporal retries forever: the run would hang, `running` in the projection. So a version this build can't
        load or compile fails the run (`version_unusable`) before any step runs, and any other exception fails it
        (`internal_error`). The workflow's outputs are evaluated under the same deadline and handlers as its steps:
        a cancel or the deadline while they're computed ends the run as it would anywhere else."""
        self.input = start
        self.started_at = workflow.info().start_time
        try:
            data = await workflow.execute_local_activity(
                LOAD_VERSION,
                LoadVersionInput(start.tenant_id, start.version_id),
                result_type=VersionData,
                start_to_close_timeout=timedelta(seconds=30),
            )
            self.program = compile_program(data.graph, data.manifests, data.expressions, data.cel_profile)
        except asyncio.CancelledError:
            await self._end_early(RunEnd("cancelled", CANCELLED))
            raise
        except Exception as e:  # its text may quote the version: the log has it, the projection names the type
            workflow.logger.error("run_version_unusable", exc_info=True)
            message = f"This build can't run the version ({type(e).__name__}); the worker's log has the details."
            return await self._end_early(RunEnd("failed", Failure(VERSION_UNUSABLE, message)))
        self.sched = Scheduler(self.program)
        deadline = self.started_at + timedelta(seconds=start.max_run_duration_s)
        outputs: dict[str, Any] | None = None
        try:
            self._prepare(start)
            await self._drive(deadline)
            end = self.sched.ended or RunEnd("failed", Failure("error", "The run ended without a result."))
            if end.status == "succeeded":
                end, outputs = await self._outputs_by(deadline, end)
        except asyncio.CancelledError:
            self.sched.end(RunEnd("cancelled", CANCELLED))
            await self._finish(RunEnd("cancelled", CANCELLED))
            raise
        except Exception as e:  # a bug: the text may quote run data, so it goes to the log, not the projection
            workflow.logger.error("run_internal_error", exc_info=True)
            message = f"The interpreter failed ({type(e).__name__}); the worker's log has the details."
            end, outputs = RunEnd("failed", Failure(INTERNAL_ERROR, message)), None
        return await self._finish(end, outputs)

    def _prepare(self, start: RunInput) -> None:
        """What the run knows before its first step: the sensitive values it can see already, and its variables."""
        self._learn(start.trigger, self.program.graph.settings.input_schema)
        for step in self.program.steps.values():  # sensitive literals in plugin configs: masked from the start
            if not step.control:
                self._learn(resolve.assemble(step.config, {}), self.program.manifests[step.ref]["config_schema"])
        schema = self.program.graph.settings.vars_schema
        self.vars = {k: p.get("default") for k, p in sorted(schema.get("properties", {}).items())}

    # --- the scheduler loop ----------------------------------------------------------------------------------------

    async def _drive(self, deadline: datetime) -> None:
        self.sched.start()
        tasks: dict[tuple[Any, ...], asyncio.Task[_Effect | None]] = {}
        waiting: list[tuple[Any, ...]] = []
        clock = asyncio.create_task(asyncio.sleep(max(0.0, (deadline - workflow.now()).total_seconds())))
        try:
            while self.sched.ended is None:
                waiting += [("step", i) for i in self.sched.take_ready()]
                waiting += [("collect", c) for c in self.sched.take_collects()]
                for inst in self.sched.take_cancels():
                    task = tasks.pop(("step", inst), None)
                    if task is not None:
                        task.cancel()
                waiting = [w for w in waiting if not self._gone(w)]
                waiting.sort(key=self._rank)
                while waiting and len(tasks) < IN_FLIGHT_CAP:
                    unit = waiting.pop(0)
                    tasks[unit] = asyncio.create_task(self._unit(unit))
                self._queue_settled()
                if self._rows and not any(key[0] == "project" for key in tasks):  # one at a time: rows wait for it
                    rows, self._rows = list(self._rows.values()), {}
                    self._projects += 1
                    tasks[("project", self._projects)] = asyncio.create_task(self._project(rows))
                if self.sched.ended is not None:
                    break
                if not tasks:
                    raise RuntimeError("nothing is running and the run hasn't ended")
                done, _ = await workflow.wait([*tasks.values(), clock], return_when=asyncio.FIRST_COMPLETED)
                self._budget.reset()
                if clock in done:
                    self.sched.end(
                        RunEnd(DEADLINE_EXCEEDED, Failure(DEADLINE_EXCEEDED, "The run passed its deadline."))
                    )
                    break
                for key in sorted((k for k, t in tasks.items() if t in done), key=self._rank):
                    effect = tasks.pop(key).result()
                    if effect is not None:
                        self._apply(key, effect)
        finally:
            clock.cancel()
            for key, task in tasks.items():
                if key[0] != "project":
                    task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)

    def _rank(self, key: tuple[Any, ...]) -> tuple[Any, ...]:
        if key[0] == "step":
            return (self.sched.order(key[1]), 0)
        if key[0] == "collect":
            c: Collect = key[1]
            return (self.sched.order(Instance(c.scope, c.loop.step)), 1)
        return ((), 2, key[1])

    def _gone(self, unit: tuple[Any, ...]) -> bool:
        """A queued step or collect whose scope has ended since: it never starts."""
        scope = self.sched.scopes.get(unit[1].scope)
        return scope is None or scope.failure is not None

    async def _unit(self, key: tuple[Any, ...]) -> _Effect | None:
        if key[0] == "step":
            self._started[key[1]] = workflow.now().isoformat()
            return await self._step(key[1])
        return await self._collect(key[1])

    def _apply(self, key: tuple[Any, ...], effect: _Effect) -> None:
        if key[0] == "collect":
            c: Collect = key[1]
            if effect.failure is not None:
                self.sched.collect_failed(c.loop, c.index, effect.failure)
            else:
                self.sched.collected(c.loop, c.index, effect.collected)
            return
        inst: Instance = key[1]
        if effect.cel_mode is not None:
            self._cel_modes[inst] = effect.cel_mode
        if effect.loop is not None:
            self.sched.open_loop(
                inst, effect.loop.items, concurrency=effect.loop.concurrency, stop_on_error=effect.loop.stop_on_error
            )
        elif effect.end is not None:
            self.sched.finish(inst, effect.end, effect.output)
        elif effect.failure is not None:
            self.sched.fail(inst, effect.failure)
        else:
            if effect.variables:
                self.vars.update(effect.variables)
            self.sched.succeed(inst, effect.output, effect.ports)

    # --- the projection -------------------------------------------------------------------------------------------

    def _queue(self, row: StepRow) -> None:
        """Queue a row for the next projection. A later row of the same attempt replaces it."""
        self._rows[(row.step_id, row.iteration_key, row.attempt)] = row

    def _learn(self, value: Any, schema: Mapping[str, Any] | None) -> None:
        self._secrets = remember(self._secrets, sensitive_values(value, schema))

    def _preview(self, value: Any, schema: Mapping[str, Any] | None = None) -> Any:
        return preview(value, schema, self._secrets)

    def _queue_settled(self) -> None:
        """Control steps that settled since the last call. Plugin steps queue their own attempts (`_activity`)."""
        now = workflow.now().isoformat()
        for inst in self.sched.take_settled():
            step = self.sched.step(inst)
            if not step.control:
                continue
            result = self.sched.scopes[inst.scope].results.get(step.key, {})
            error = result.get("error")
            self._queue(
                StepRow(
                    run_id=self.input.run_id,
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

    # --- values ----------------------------------------------------------------------------------------------------

    def _view(self, scope: ScopeKey, item: tuple[Any, int] | None = None) -> Any:
        run = {
            "id": self.input.run_id,
            "started_at": self.started_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "now": workflow.now().astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        return resolve.view(
            self.sched, scope, trigger=self.input.trigger, variables=dict(self.vars), run=run, item=item
        )

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
            if self._budget.must_yield(task.record):
                await asyncio.sleep(0.001)  # a durable timer: the workflow task ends here (spec §5.6)
                self._budget.reset()
            outcomes = task.run_local()
            for _ in outcomes:
                self._budget.charge(task.record)
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
                    schedule_to_start_timeout=timedelta(seconds=self.input.cel_schedule_to_start_s),
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
        if not self.sched.debit(len(items)):
            return _Effect(failure=Failure(ITERATION_CAP_EXCEEDED, "This run reached its limit of loop iterations."))
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
        return _Effect(collected=resolve.assemble({"collect": collect}, values)["collect"])

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
                run_id=self.input.run_id,
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
                        tenant_id=self.input.tenant_id,
                        run_id=self.input.run_id,
                        step_id=str(step.id),
                        node_key=step.key,
                        iteration_key=iteration_key(inst.scope),
                        ref=step.ref,
                        config=config,
                        mode=self.input.mode,
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
                run_id=self.input.run_id,
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

    # --- the end ---------------------------------------------------------------------------------------------------

    async def _outputs_by(self, deadline: datetime, end: RunEnd) -> tuple[RunEnd, dict[str, Any] | None]:
        """The workflow's outputs, within the run's deadline. Past it, their evaluation is cancelled and the run ends
        `deadline_exceeded`; an output that can't be computed fails the run with its code."""
        task = asyncio.create_task(self._outputs())
        clock = asyncio.create_task(asyncio.sleep(max(0.0, (deadline - workflow.now()).total_seconds())))
        try:
            done, _ = await workflow.wait([task, clock], return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:  # the run was cancelled: so is what it was computing
            task.cancel()
            clock.cancel()
            raise
        clock.cancel()
        if task not in done:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return RunEnd(DEADLINE_EXCEEDED, Failure(DEADLINE_EXCEEDED, "The run passed its deadline.")), None
        try:
            return end, task.result()
        except resolve.ValueFailure as e:
            return RunEnd("failed", e.failure), None

    async def _finish(self, end: RunEnd, outputs: dict[str, Any] | None = None) -> RunResult:
        error = end.failure.to_json() if end.failure is not None and end.status != "succeeded" else None
        if error is not None:
            error["message"] = mask(error["message"], self._secrets)
        summary = RunSummary(
            run_id=self.input.run_id,
            status=end.status,
            ended_at=workflow.now().isoformat(),
            error_code=error["code"] if error else None,
            error_message=error["message"] if error else None,
            iterations=self.sched.iterations,
        )
        self._queue_settled()
        rows, self._rows = list(self._rows.values()), {}
        await self._project_end(rows, summary)
        return RunResult(status=end.status, outputs=outputs, error=error, iterations=self.sched.iterations)

    async def _end_early(self, end: RunEnd) -> RunResult:
        """The run ends before it has a program: nothing ran, so only the run is projected."""
        error = end.failure.to_json() if end.failure is not None else None
        summary = RunSummary(
            run_id=self.input.run_id,
            status=end.status,
            ended_at=workflow.now().isoformat(),
            error_code=error["code"] if error else None,
            error_message=error["message"] if error else None,
        )
        await self._project_end([], summary)
        return RunResult(status=end.status, error=error)

    async def _outputs(self) -> dict[str, Any]:
        settings_outputs = self.program.graph.settings.outputs
        pairs = [(pointer_str(p), v) for p, v in iter_values(settings_outputs, ("settings", "outputs"))]
        values, _ = await self._values(None, pairs, ())
        assembled = resolve.assemble({"settings": {"outputs": settings_outputs}}, values)
        return dict(assembled["settings"]["outputs"])

    async def _project_end(self, rows: list[StepRow], summary: RunSummary) -> None:
        """The run's last projection. A cancel that arrives while it's written comes too late to unmake the end it
        records: the write is repeated and the run's result stands, so the projection and Temporal agree."""
        try:
            await self._project(rows, summary)
        except asyncio.CancelledError:
            await self._project(rows, summary)

    async def _project(self, rows: list[StepRow], summary: RunSummary | None = None) -> None:
        await workflow.execute_activity(
            PROJECT,
            ProjectInput(self.input.tenant_id, rows, summary),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_interval=timedelta(seconds=30)),
        )
        return None


__all__ = [
    "CEL_BATCH",
    "DEADLINE_EXCEEDED",
    "INTERNAL_ERROR",
    "IN_FLIGHT_CAP",
    "NODE_TYPE_UNAVAILABLE",
    "VERSION_UNUSABLE",
    "RunGraph",
]
