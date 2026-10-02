# SPDX-License-Identifier: Apache-2.0
"""The two workflow types on `dewpoint-engine` (spec §6, §7):
- `RunGraph` runs a pinned version: a run the dispatcher started, a sub-flow (`run_workflow`) and a failure handler.
  A sub-flow and a failure handler are runs of their own: each writes its row first, points at its parent run, and
  draws its iterations from its parent.
- `LoopBatch` runs a slice of a loop over more than 100 items, as a child of the execution that holds the loop.

Both drive the shared `Execution` loop, and both may continue-as-new at a quiescent point, carrying a snapshot."""

import asyncio
import traceback
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import VersioningBehavior
from temporalio.exceptions import ApplicationError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from dewpoint.engine.graph.values import iter_values, pointer_str
    from dewpoint.engine.handles import contains_marker
    from dewpoint.engine.runtime.activities import (
        FAILURE_HANDLER,
        LOAD_VERSION,
        SUBFLOW,
        BatchInput,
        BatchResult,
        LoadVersionInput,
        Parent,
        RunInput,
        RunResult,
        RunStart,
        RunSummary,
        VersionData,
    )
    from dewpoint.engine.runtime.budget import Budget
    from dewpoint.engine.runtime.execution import (
        CANCELLED,
        CEL_BATCH,
        CONTINUE,
        DEADLINE_EXCEEDED,
        IN_FLIGHT_CAP,
        INTERNAL_ERROR,
        NODE_TYPE_UNAVAILABLE,
        PROJECT_BYTES,
        SUBFLOW_GRANT,
        VERSION_UNUSABLE,
        Execution,
        _cancelled,
        _unloadable,
        child_options,
        program_of,
    )
    from dewpoint.engine.runtime.ids import run_of, run_workflow_id, tenant_of
    from dewpoint.engine.runtime.program import Program

    # by the module's own name: `from <package> import <module>` loads a copy inside the sandbox, the package being
    # loaded there already, and its ValueFailure isn't the one the interpreter raises
    from dewpoint.engine.runtime.resolve import ValueFailure, assemble
    from dewpoint.engine.runtime.scheduler import (
        ITERATION_CAP,
        SNAPSHOT_FORMAT,
        Failure,
        ItemsRef,
        OuterScope,
        RunEnd,
        Scheduler,
    )
    from dewpoint.engine.runtime.size import (
        BATCH_RESULTS_TOO_LARGE,
        BATCH_SNAPSHOT_TOO_LARGE,
        HANDLER_INPUT_TOO_LARGE,
        OUTPUTS_TOO_LARGE,
        PAYLOAD_TOO_LARGE,
        RESULT_TOO_LARGE,
        RUN_SNAPSHOT_TOO_LARGE,
        SNAPSHOT_TOO_LARGE,
        encoded_bytes,
        fits,
        payload_bytes,
        snapshot_fits,
    )


HANDLED = ("failed", DEADLINE_EXCEEDED)  # the ends that run a failure handler (a cancel is no failure)
WHERE_FRAMES = 8  # the innermost frames a bug's log names, as the activities' (apps.worker.logs)


def _bug(e: BaseException) -> dict[str, Any]:
    """A workflow bug's log fields (engine 2b spec §6.7): its type and where it was raised, never its text, which may
    quote the run's data. No plugin code runs in the workflow, so its exceptions' types and frames are code."""
    frames = traceback.walk_tb(e.__traceback__)
    where = [f"{f.f_code.co_filename.rsplit('/', 1)[-1]}:{f.f_code.co_name}:{line}" for f, line in frames]
    return {"error_type": type(e).__name__, "where": where[-WHERE_FRAMES:]}


def _same_run(tenant_id: str, run_id: str) -> None:
    """The start's tenant and run are the ones its server-built workflow id names (engine 2b spec §6.1). Every store
    write is scoped by the start's tenant, so a start that disagrees is refused before anything runs: only a bug, or a
    start built outside Dewpoint, gets here."""
    workflow_id = workflow.info().workflow_id
    if tenant_of(workflow_id) != tenant_id or run_of(workflow_id) != run_id:
        raise ApplicationError(
            "This run's workflow id doesn't name its tenant and run.", type=INTERNAL_ERROR, non_retryable=True
        )


@workflow.defn(name="RunGraph", versioning_behavior=VersioningBehavior.PINNED)  # spec §7
class RunGraph(Execution):
    @workflow.run
    async def run(self, start: RunInput) -> RunResult:
        """Every way a run ends is projected. Python exceptions in workflow code would fail the workflow task, which
        Temporal retries forever: the run would hang, `running` in the projection. So a version this build can't
        load or compile fails the run (`version_unusable`) before any step runs, and any other exception fails it
        (`internal_error`). The workflow's outputs are evaluated under the same deadline and handlers as its steps:
        a cancel or the deadline while they're computed ends the run as it would anywhere else.

        A child run (a sub-flow, a failure handler) writes its own row before anything else, even its version's
        load, so every way it ends has a row to record it. It shares its parent's deadline (a failure handler has
        its own), and, cancelled, returns its result instead of ending cancelled, so its parent learns how many
        iterations it used.

        A run that ends `failed` or `deadline_exceeded` then runs its failure handler once. Its end is decided
        first, and stands: a cancel meanwhile cancels the handler, which reports back. But its row stays
        non-terminal until the handler has ended, so something non-terminal always holds the handler's closure,
        and with it the CEL profiles it pins (spec §4.5). The end is recorded once, counting the handler's
        iterations."""
        _same_run(start.tenant_id, start.run_id)
        snapshot = start.snapshot
        unreadable = snapshot is not None and snapshot.get("snapshot_format") != SNAPSHOT_FORMAT
        if unreadable:
            snapshot = None  # nothing of it is read: the run ends below
        started = datetime.fromisoformat(snapshot["run_started_at"]) if snapshot else workflow.info().start_time
        if snapshot is not None:
            deadline = datetime.fromisoformat(snapshot["deadline"])
        elif start.parent is not None and start.parent.kind != FAILURE_HANDLER:
            deadline = datetime.fromisoformat(start.parent.deadline)
        else:
            deadline = started + timedelta(seconds=start.max_run_duration_s)
        self._context(
            tenant_id=start.tenant_id,
            run_id=start.run_id,
            version_id=start.version_id,
            mode=start.mode,
            trigger=start.trigger,
            cel_schedule_to_start_s=start.cel_schedule_to_start_s,
            max_run_duration_s=start.max_run_duration_s,
            parent=start.parent,
            run_started_at=started,
            deadline=deadline,
            checkpoint_events=start.checkpoint_events,
            drain_events=start.drain_events,
        )
        self.input = start
        if unreadable:  # a snapshot this build can't read: the run ends, it never hangs (spec §6)
            message = "This build can't read the run's continue-as-new snapshot."
            return await self._end_early(RunEnd("failed", Failure(INTERNAL_ERROR, message)), start.iterations)
        if start.parent is not None and snapshot is None:  # its row first: whatever ends it now has a row to end
            if await self._shielded([], None, RunStart.of(start, started.isoformat())):
                return await self._cancelled_early(start.iterations)  # cancelled while the row was written
        try:
            data = await workflow.execute_local_activity(
                LOAD_VERSION,
                LoadVersionInput(start.tenant_id, start.version_id),
                result_type=VersionData,
                start_to_close_timeout=timedelta(seconds=30),
            )
        except asyncio.CancelledError:
            return await self._cancelled_early(start.iterations)
        except Exception as e:
            if _cancelled(e):
                return await self._cancelled_early(start.iterations)
            workflow.logger.error("run_version_unusable", extra=_bug(e))
            return await self._end_early(RunEnd("failed", Failure(VERSION_UNUSABLE, _unloadable(e))), start.iterations)
        self._charge_sent(data)  # its marker goes out with this workflow task's commands (engine 2b spec §5.2)
        try:
            program = program_of(data)  # compiled once per worker process (engine 2b spec §5.3)
        except Exception as e:
            workflow.logger.error("run_version_unusable", extra=_bug(e))
            message = f"This build can't run the version ({type(e).__name__}); the worker's log has the details."
            return await self._end_early(RunEnd("failed", Failure(VERSION_UNUSABLE, message)), start.iterations)
        outputs: dict[str, Any] | None = None
        try:
            if snapshot is not None:
                await self._restore(program, snapshot)
            else:
                self._fresh(program)
            if await self._drive() == CONTINUE:
                await self._flush()
                continued = replace(start, snapshot=await self._snapshot(), iterations=self.sched.iterations)
                if snapshot_fits(continued, workflow.payload_converter()):
                    await self._send(continued)
                    workflow.continue_as_new(continued)
                # engine 2b spec §5.3: too large to carry on, the run ends here, cleanly (2b-1b bounds the state)
                self.sched.end(RunEnd("failed", Failure(SNAPSHOT_TOO_LARGE, RUN_SNAPSHOT_TOO_LARGE)))
            end = self.sched.ended or RunEnd("failed", Failure("error", "The run ended without a result."))
            if end.status == "succeeded":
                end, outputs = await self._outputs_by(end)
            if outputs is not None and not self._returnable(outputs):  # checked here, where the result is made
                end, outputs = RunEnd("failed", Failure(PAYLOAD_TOO_LARGE, OUTPUTS_TOO_LARGE)), None
            if outputs is not None and start.parent is not None and start.parent.kind == SUBFLOW:
                # its parent reads the handles in them through a grant, made before the result returns (2b spec §3.4)
                refused = await self._grant(start.parent.run_id, outputs) if contains_marker(outputs) else None
                if refused is not None:
                    end, outputs = RunEnd("failed", refused), None
        except asyncio.CancelledError:
            self.sched.end(RunEnd("cancelled", CANCELLED))
            result = await self._finish(RunEnd("cancelled", CANCELLED))
            if start.parent is None:
                raise
            return result  # a child reports back instead: its parent learns what it used
        except Exception as e:  # a bug: the text may quote run data, so it goes to the log, not the projection
            workflow.logger.error("run_internal_error", extra=_bug(e))
            message = f"The interpreter failed ({type(e).__name__}); the worker's log has the details."
            end, outputs = RunEnd("failed", Failure(INTERNAL_ERROR, message)), None
        ended = workflow.now()  # the end is decided: whatever follows, it stands
        pin = self._handler_pin(data) if end.status in HANDLED else None
        if pin is not None and not await self._project_end(None):  # its rows land; its end waits for the handler
            await self._failure_handler(pin, data, self._end_error(end))  # (a cancel meanwhile: no handler)
        return await self._finish(end, outputs, ended)

    def _fresh(self, program: Program) -> None:
        """A new run's state: its budget (the cap, or what its parent granted) and its variables. Its sensitive values
        are handles already (engine 2b spec §3.5): nothing here holds one to learn."""
        self.program = program
        parent = self.parent
        budget = Budget(ITERATION_CAP, root=True) if parent is None else Budget(parent.grant, root=False)
        self.sched = Scheduler(program, budget=budget, prefix=workflow.info().workflow_id)
        schema = program.graph.settings.vars_schema
        self.sched.init_vars({k: p.get("default") for k, p in sorted(schema.get("properties", {}).items())})
        self.sched.start()

    async def _outputs_by(self, end: RunEnd) -> tuple[RunEnd, dict[str, Any] | None]:
        """The workflow's outputs, within the run's deadline. Past it, their evaluation is cancelled and the run ends
        `deadline_exceeded`; an output that can't be computed fails the run with its code."""
        task = asyncio.create_task(self._outputs())
        clock = asyncio.create_task(asyncio.sleep(max(0.0, (self.deadline - workflow.now()).total_seconds())))
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
        except ValueFailure as e:
            return RunEnd("failed", e.failure), None

    def _returnable(self, outputs: dict[str, Any]) -> bool:
        """The run's result, with these outputs, within Temporal's payload limit (engine 2b spec §5.2). Past it,
        Temporal would refuse to record the result, and the workflow task would retry until the deadline."""
        result = RunResult("succeeded", outputs, None, self.sched.iterations)
        return fits(result, workflow.payload_converter())

    async def _outputs(self) -> dict[str, Any]:
        settings_outputs = self.program.graph.settings.outputs
        pairs = [(pointer_str(p), v) for p, v in iter_values(settings_outputs, ("settings", "outputs"))]
        values, _ = await self._values(None, pairs, ())
        assembled = assemble({"settings": {"outputs": settings_outputs}}, values)
        return dict(assembled["settings"]["outputs"])

    async def _finish(
        self, end: RunEnd, outputs: dict[str, Any] | None = None, ended: datetime | None = None
    ) -> RunResult:
        end, result = self._final(end, outputs, self.sched.iterations)
        summary = RunSummary(
            run_id=self.run_id,
            status=end.status,
            ended_at=(ended or workflow.now()).isoformat(),
            error_code=result.error["code"] if result.error else None,
            error_message=result.error["message"] if result.error else None,
            iterations=self.sched.iterations,
        )
        await self._project_end(summary)
        return await self._returned(result)

    def _final(self, end: RunEnd, outputs: dict[str, Any] | None, iterations: int) -> tuple[RunEnd, RunResult]:
        """The run's end and its result, checked before either is recorded: every way a run ends returns through
        here (engine 2b spec §5.2). Outputs were checked where they were made, and everything else a result carries
        is bounded (a stored message), so a result past the limit anyway is a bug: the run ends as one,
        with no outputs, so nothing it returns needs masking by its parent, and its workflow task never retries."""
        result = RunResult(end.status, outputs, self._end_error(end), iterations)
        if fits(result, workflow.payload_converter()):
            return end, result
        workflow.logger.error("run_result_too_large")
        end = RunEnd("failed", Failure(INTERNAL_ERROR, RESULT_TOO_LARGE))
        return end, RunResult(end.status, None, self._end_error(end), iterations)

    def _end_error(self, end: RunEnd) -> dict[str, Any] | None:
        """The run's error as it's stored: its summary, its result and its failure handler's trigger all say this."""
        error = end.failure.to_json() if end.failure is not None and end.status != "succeeded" else None
        return self._stored(error)

    async def _end_early(self, end: RunEnd, iterations: int) -> RunResult:
        """The run ends before it has a program: nothing ran in this execution, so only the run is projected, with
        what it used before continuing as new (`iterations`)."""
        end, result = self._final(end, None, iterations)
        summary = RunSummary(
            run_id=self.run_id,
            status=end.status,
            ended_at=workflow.now().isoformat(),
            error_code=result.error["code"] if result.error else None,
            error_message=result.error["message"] if result.error else None,
            iterations=iterations,
        )
        await self._shielded([], summary)
        return await self._returned(result)

    async def _cancelled_early(self, iterations: int) -> RunResult:
        """Cancelled before the run restored its snapshot or started: it reports what it used before continuing as new
        (`iterations`), as `_end_early` does."""
        result = await self._end_early(RunEnd("cancelled", CANCELLED), iterations)
        if self.parent is None:
            raise asyncio.CancelledError
        return result

    def _handler_pin(self, data: VersionData) -> tuple[str, str] | None:
        """The failure handler this run's version pins, as (version id, workflow id); none for a failure handler's
        own run, whose failure runs no handler."""
        version, workflow_id = data.failure_handler_version_id, self.program.graph.settings.failure_handler
        if version is None or workflow_id is None or (self.parent is not None and self.parent.kind == FAILURE_HANDLER):
            return None
        return version, str(workflow_id)

    async def _failure_handler(self, pin: tuple[str, str], data: VersionData, error: dict[str, Any] | None) -> None:
        """The run's failure handler (spec §6): its pinned version runs once, as a child run, with the error summary as
        its trigger, and draws on this run's budget. Its end doesn't change this run's.

        This run's end is already decided: a cancel meanwhile comes too late to change it. It cancels the handler,
        which reports back first, so its iterations still count."""
        version, workflow_id = pin
        child_run = str(workflow.uuid4())
        child = run_workflow_id(self.tenant_id, child_run)  # its workflow id, and its key in this budget
        grant = self.sched.budget.start_child(child, SUBFLOW_GRANT)
        parent = Parent(
            workflow_id=workflow.info().workflow_id,
            run_id=self.run_id,
            step_id="",
            iteration_key="",
            kind=FAILURE_HANDLER,
            deadline=(workflow.now() + timedelta(seconds=self.max_run_duration_s)).isoformat(),
            grant=grant,
            depth=self.depth + 1,
            root_run_id=self.root_run_id,
        )
        trigger = {
            "run_id": self.run_id,
            "workflow_id": data.workflow_id,
            "version_id": self.version_id,
            "error": {"code": (error or {}).get("code"), "message": (error or {}).get("message")},
        }
        run = RunInput(
            self.tenant_id,
            child_run,
            version,
            trigger,
            self.mode,
            self.max_run_duration_s,
            self.cel_schedule_to_start_s,
            parent=parent,
            workflow_id=workflow_id,
            checkpoint_events=self.checkpoint_events,
            drain_events=self.drain_events,
        )
        converter = workflow.payload_converter()
        if not fits(run, converter):  # its largest values spill first, granted to it (engine 2b spec §3.4, §5.2)
            room = payload_bytes() - encoded_bytes(replace(run, trigger={}), converter) - 16
            fitted = await self._fit(trigger, room, f"handler/{child_run}")
            refused = fitted if isinstance(fitted, Failure) else await self._grant(child_run, fitted)
            if refused is None:
                run = replace(run, trigger=fitted)
        if not fits(run, converter):  # never sent; its row says why
            self.sched.budget.settle_child(child, 0)
            failure = Failure(PAYLOAD_TOO_LARGE, HANDLER_INPUT_TOO_LARGE)
            await self._lost_end(run, workflow.now().isoformat(), failure)
            await self._send_signals()
            return
        handler = asyncio.create_task(self._handler(run, child))
        while not handler.done():  # it draws its iterations from this run: answer as it asks
            wake = asyncio.create_task(workflow.wait_condition(lambda: bool(self._mail or self._answers)))
            try:
                await workflow.wait([handler, wake], return_when=asyncio.FIRST_COMPLETED)
            except asyncio.CancelledError:  # this run's end stands: the handler is cancelled, and reports back
                handler.cancel()
            finally:
                wake.cancel()
            self._serve_budget()
        self.sched.budget.settle_child(child, None if handler.cancelled() else handler.result())
        await self._send_signals()

    async def _handler(self, run: RunInput, child: str) -> int | None:
        """The failure handler's run: the iterations it used, or None when it ended without saying (its end is then
        written here, as a sub-flow's is)."""
        started = workflow.now().isoformat()
        try:
            await self._send(run)
        except asyncio.CancelledError:  # cancelled before it was sent: it never ran
            return 0
        try:
            result: RunResult = await workflow.execute_child_workflow(
                "RunGraph", run, result_type=RunResult, **child_options(child)
            )
        except ChildWorkflowError as e:
            workflow.logger.warning("failure_handler_failed", extra=_bug(e))
            await self._lost_end(run, started, self._lost("failure handler", e))
            return None
        return result.iterations


@workflow.defn(name="LoopBatch", versioning_behavior=VersioningBehavior.PINNED)
class LoopBatch(Execution):
    @workflow.run
    async def run(self, start: BatchInput) -> BatchResult:
        """A slice of a loop, run as a child of the execution that holds the loop (spec §6). Its iterations run as
        they would inline, with the loop's concurrency and error policy, over read-only copies of the scopes around
        the loop; their rows go into the parent's run. It returns what they collected, the failures, and how many
        iterations it used. A fail or stop node, or the deadline, ends the run: the batch reports it as `end`."""
        _same_run(start.tenant_id, start.run_id)
        snapshot = start.snapshot
        if snapshot is not None and snapshot.get("snapshot_format") != SNAPSHOT_FORMAT:  # it can't carry on: fail
            message = "This build can't read the batch's continue-as-new snapshot."  # its loop (decision 4)
            raise ApplicationError(message, type=INTERNAL_ERROR, non_retryable=True)
        deadline = snapshot["deadline"] if snapshot else start.parent.deadline
        self._context(
            tenant_id=start.tenant_id,
            run_id=start.run_id,
            version_id=start.version_id,
            mode=start.mode,
            trigger=start.trigger,
            cel_schedule_to_start_s=start.cel_schedule_to_start_s,
            max_run_duration_s=0,
            parent=start.parent,
            run_started_at=datetime.fromisoformat(start.run_started_at),
            deadline=datetime.fromisoformat(deadline),
            checkpoint_events=start.checkpoint_events,
            drain_events=start.drain_events,
        )
        try:
            data = await workflow.execute_local_activity(
                LOAD_VERSION,
                LoadVersionInput(start.tenant_id, start.version_id),
                result_type=VersionData,
                start_to_close_timeout=timedelta(seconds=30),
            )
            program = program_of(data)  # compiled once per worker process (engine 2b spec §5.3)
        except asyncio.CancelledError:
            return BatchResult([], [], end=RunEnd("cancelled", CANCELLED).to_json(), iterations=start.iterations)
        except Exception as e:
            if _cancelled(e):
                return BatchResult([], [], end=RunEnd("cancelled", CANCELLED).to_json(), iterations=start.iterations)
            workflow.logger.error("batch_version_unusable", extra=_bug(e))
            message = f"This build can't run the version ({type(e).__name__}); the worker's log has the details."
            raise ApplicationError(message, type=VERSION_UNUSABLE, non_retryable=True) from None
        self._charge_sent(data)  # its marker goes out with this workflow task's commands (engine 2b spec §5.2)
        try:
            if snapshot is not None:
                await self._restore(program, snapshot)
            else:
                self.program = program
                self.sched = Scheduler(
                    program, budget=Budget(start.parent.grant, root=False), prefix=workflow.info().workflow_id
                )
                self.sched.init_vars(dict(start.variables))
                outer = [
                    OuterScope(
                        tuple((str(k), int(i)) for k, i in o["key"]),
                        o["results"],
                        o["item"],
                        o["index"],
                        o.get("chain"),
                        o.get("claimed", ""),
                    )
                    for o in start.outer
                ]
                self.sched.start_batch(
                    uuid.UUID(start.loop_step),
                    outer,
                    ItemsRef.from_json(start.items_ref) if start.items_ref else start.items,
                    offset=start.offset,
                    concurrency=start.concurrency,
                    stop_on_error=start.stop_on_error,
                    base=start.collect_base,
                )
            if await self._drive() == CONTINUE:
                await self._flush()
                # each value travels once (engine 2b spec §5.3): the snapshot holds the slice, the enclosing scopes and
                # the variables, so the continued input carries none of them again
                continued = replace(
                    start,
                    snapshot=await self._snapshot(),
                    iterations=self.sched.iterations,
                    items=[],
                    items_ref=None,
                    outer=[],
                    variables={},
                )
                if snapshot_fits(continued, workflow.payload_converter()):
                    await self._send(continued)
                    workflow.continue_as_new(continued)
                # engine 2b spec §5.3: too large to carry on, the batch ends here and its loop fails
                stopped = Failure(SNAPSHOT_TOO_LARGE, BATCH_SNAPSHOT_TOO_LARGE).to_json()
                return await self._returned(
                    self._checked(BatchResult([], [], stopped, iterations=self.sched.iterations))
                )
        except asyncio.CancelledError:
            self.sched.end(RunEnd("cancelled", CANCELLED))
            await self._project_end(None)
            return await self._returned(self._result(RunEnd("cancelled", CANCELLED)))
        except Exception as e:
            workflow.logger.error("batch_internal_error", extra=_bug(e))
            await self._project_end(None)  # its steps' rows land first, as a run's do
            message = f"The batch failed ({type(e).__name__}); the worker's log has the details."
            raise ApplicationError(message, type=INTERNAL_ERROR, non_retryable=True) from None
        await self._project_end(None)
        return await self._returned(self._result(self.sched.ended))

    def _result(self, end: RunEnd | None) -> BatchResult:
        outcome = self.sched.outcome
        if outcome is None:  # the run ended inside the batch
            end = end or RunEnd("failed", Failure("error", "The batch ended without a result."))
            ended = BatchResult([], [], end=end.to_json(), iterations=self.sched.iterations)
            return self._checked(ended)
        result = BatchResult(
            collected=outcome.collected,
            failures=outcome.failures,
            collection=outcome.collection,
            failure_collection=outcome.failure_collection,
            stopped=outcome.stopped.to_json() if outcome.stopped else None,
            iterations=self.sched.iterations,
        )
        if fits(result, workflow.payload_converter()):
            return result
        # Temporal would refuse to record it (engine 2b spec §5.2): the loop fails instead, and no collected item is
        # dropped silently. The iterations it used still reach the parent.
        stopped = Failure(PAYLOAD_TOO_LARGE, BATCH_RESULTS_TOO_LARGE)
        return self._checked(BatchResult([], [], stopped.to_json(), iterations=self.sched.iterations))

    def _checked(self, result: BatchResult) -> BatchResult:
        """A result with nothing collected carries only an error and the bounded sensitive values, so past the limit
        anyway is a bug (engine 2b spec §5.2): the batch fails its loop as one, with nothing its parent would need to
        mask, and its workflow task never retries."""
        if fits(result, workflow.payload_converter()):
            return result
        workflow.logger.error("batch_result_too_large")
        stopped = Failure(INTERNAL_ERROR, RESULT_TOO_LARGE).to_json()
        return BatchResult([], [], stopped, iterations=result.iterations)


__all__ = [
    "CEL_BATCH",
    "DEADLINE_EXCEEDED",
    "INTERNAL_ERROR",
    "IN_FLIGHT_CAP",
    "NODE_TYPE_UNAVAILABLE",
    "PROJECT_BYTES",
    "VERSION_UNUSABLE",
    "LoopBatch",
    "RunGraph",
]
