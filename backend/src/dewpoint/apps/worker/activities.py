# SPDX-License-Identifier: Apache-2.0
"""The activities `RunGraph` names (engine/runtime/activities.py), over a `RunStore`: the database in production, a
dict in tests.

A plugin step's activity runs **one attempt** of its node and writes nothing (spec §3, parent §6.6). `RunGraph`
schedules each attempt itself, decides whether to retry, and projects every attempt's rows, so a row write can
never repeat an effect, and a timeout after an ambiguous send is never retried. The attempt:
- validates the config before `run()` and the output after; a mismatch is fatal (`config_invalid`,
  `output_schema_violation`);
- calls `simulate()` in a simulated run, and records `simulated`;
- maps `RetryableError` to retryable, `FatalError` to fatal, and `OutcomeUnknownError` to `outcome_unknown`, never
  retried;
- maps any other exception to `unexpected_error`, retryable, except from an `ambiguous` node, where the request may
  have been sent: `outcome_unknown`;
- for a `reconcilable` node on attempt 2 or later, calls `reconcile()` first and keeps what it finds.

The projection is tenant-readable, so a message never quotes input: a validation error names each field and its
rule's code, and an unexpected exception names only its type. Its text goes to the worker's log."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, Protocol, get_args

import structlog
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError
from pydantic_core.core_schema import ErrorType
from temporalio import activity
from temporalio.exceptions import ApplicationError

from dewpoint.apps.cel_client import EvaluatorUnavailable, evaluate_remote
from dewpoint.apps.worker.context import context
from dewpoint.engine.cel import ipc
from dewpoint.engine.runtime.activities import (
    APPLIED,
    CEL_EVALUATE,
    LOAD_VERSION,
    OUTCOME_UNKNOWN,
    PROJECT,
    SIMULATE,
    SIMULATED,
    CelInput,
    CelResult,
    LoadVersionInput,
    ProjectInput,
    StepInput,
    StepResult,
    VersionData,
    step_activity,
)
from dewpoint.engine.runtime.projection import location
from dewpoint.sdk import (
    FatalError,
    Node,
    NodeKind,
    OutcomeUnknownError,
    Plugin,
    RetryableError,
    SideEffect,
    dump_output,
    node_manifest,
)

CONFIG_INVALID = "config_invalid"
OUTPUT_SCHEMA_VIOLATION = "output_schema_violation"
SIMULATION_UNAVAILABLE = "simulation_unavailable"
UNEXPECTED_ERROR = "unexpected_error"
INVALID_REQUEST = "invalid_request"
_log = structlog.get_logger("dewpoint.worker")
_PYDANTIC_CODES = frozenset(get_args(ErrorType))  # every built-in validation error type


class RunStore(Protocol):
    async def version(self, tenant_id: str, version_id: str) -> VersionData: ...
    async def project(self, data: ProjectInput) -> None: ...


class _StepFailed(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool, outcome: str | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.retryable, self.outcome = code, message, retryable, outcome


def _fields(error: ValidationError, schema: Mapping[str, Any]) -> str:
    """Each failing field and its rule's stable code (`int_parsing`, `value_error`), nothing else: pydantic's
    messages quote the input, and so does a validator's own prose, whatever `include_input` says. A location shows
    only what the schema declares at each place (`projection.location`): a map key is data, even a numeric one. A
    code shows only if pydantic defines it: a custom error's type is whatever its validator made it."""
    problems = error.errors(include_url=False, include_context=False, include_input=False)
    return "; ".join(f"{location(e['loc'], schema)} ({_code(e['type'])})" for e in problems) + "."


def _code(error_type: str) -> str:
    return error_type if error_type in _PYDANTIC_CODES else "custom_error"


async def _call(node: type[Node], step: StepInput, schema: Mapping[str, Any]) -> tuple[BaseModel, str]:
    try:
        config = node.Config.model_validate(step.config)
    except ValidationError as e:
        message = f"The config doesn't match `{step.ref}`: {_fields(e, schema)}"
        raise _StepFailed(CONFIG_INVALID, message, retryable=False) from None
    ctx = context(step.tenant_id, step.run_id, step.step_id, step.iteration_key, step.attempt)
    instance = node()
    try:
        if step.mode == SIMULATE:
            return await instance.simulate(ctx, config), SIMULATED
        if node.side_effect == SideEffect.RECONCILABLE and step.attempt > 1:
            found = await instance.reconcile(ctx, config)
            if found is not None:
                return found, APPLIED
        return await instance.run(ctx, config), APPLIED
    except OutcomeUnknownError as e:
        raise _StepFailed(e.code, e.message, retryable=False, outcome=OUTCOME_UNKNOWN) from None
    except FatalError as e:
        raise _StepFailed(e.code, e.message, retryable=False) from None
    except RetryableError as e:
        raise _StepFailed(e.code, e.message, retryable=True) from None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        if isinstance(e, NotImplementedError) and step.mode == SIMULATE:
            raise _StepFailed(SIMULATION_UNAVAILABLE, f"`{step.ref}` can't be simulated.", retryable=False) from None
        _log.warning(
            "step_unexpected_error",
            run_id=step.run_id,
            step_id=step.step_id,
            iteration_key=step.iteration_key,
            attempt=step.attempt,
            error_type=type(e).__name__,
            error=str(e)[:500],
        )
        message = f"The node raised {type(e).__name__}."
        if node.side_effect == SideEffect.AMBIGUOUS:
            raise _StepFailed(OUTCOME_UNKNOWN, message, retryable=False, outcome=OUTCOME_UNKNOWN) from None
        raise _StepFailed(UNEXPECTED_ERROR, message, retryable=True) from None


def step_activity_for(node: type[Node]) -> Callable[[StepInput], Awaitable[StepResult]]:
    ref = f"{node.type}@{node.version}"
    config_schema = node.Config.model_json_schema(mode="validation")
    output_schema = node_manifest(node)["output_schema"]  # what the node promises to emit: serialized and closed
    emitted = Draft202012Validator(output_schema)

    @activity.defn(name=step_activity(ref))
    async def run_step(step: StepInput) -> StepResult:
        try:
            result, outcome = await _call(node, step, config_schema)
            if not isinstance(result, BaseModel):
                return StepResult(dump_output(node.Output.model_validate(result)), outcome)
            # pydantic trusts instances it didn't build (`model_construct`, assignment): check what the instance emits
            # against the declared output schema, not against the model's input types (a field serializer may change
            # them)
            data = result.model_dump(mode="json", by_alias=True, warnings=False)
            problems = sorted(emitted.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])
            if problems:
                where = "; ".join(f"{location(list(e.absolute_path), output_schema)} ({e.validator})" for e in problems)
                message = f"The output doesn't match `{ref}`: {where}."
                raise ApplicationError(message, {"outcome": None}, type=OUTPUT_SCHEMA_VIOLATION, non_retryable=True)
            return StepResult(data, outcome)
        except _StepFailed as f:
            details = {"outcome": f.outcome}
            raise ApplicationError(f.message, details, type=f.code, non_retryable=not f.retryable) from None
        except PydanticSerializationError:
            message = f"The output doesn't match `{ref}`: it can't be written as JSON."
            raise ApplicationError(
                message, {"outcome": None}, type=OUTPUT_SCHEMA_VIOLATION, non_retryable=True
            ) from None
        except ValidationError as e:
            message = f"The output doesn't match `{ref}`: {_fields(e, output_schema)}"
            raise ApplicationError(
                message, {"outcome": None}, type=OUTPUT_SCHEMA_VIOLATION, non_retryable=True
            ) from None

    return run_step


def engine_activities(store: RunStore, plugins: Iterable[Plugin]) -> list[Callable[..., Any]]:
    """Everything the engine queue serves: the version loader, the projection, and one activity per action node."""

    @activity.defn(name=LOAD_VERSION)
    async def load_version(data: LoadVersionInput) -> VersionData:
        return await store.version(data.tenant_id, data.version_id)

    @activity.defn(name=PROJECT)
    async def project(data: ProjectInput) -> None:
        await store.project(data)

    steps = [step_activity_for(node) for plugin in plugins for node in plugin.nodes if node.kind == NodeKind.ACTION]
    return [load_version, project, *steps]


Evaluate = Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]]


def remote_evaluator(socket_path: str, profile: str) -> Evaluate:
    """Evaluate through the cel-evaluator on `socket_path` (spec §5.7)."""

    async def evaluate(request: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            parsed = ipc.parse_request(request)
        except ipc.FrameError as e:  # a request no retry can fix
            raise ApplicationError(f"not an evaluate request: {e}", type=INVALID_REQUEST, non_retryable=True) from None
        if not isinstance(parsed, ipc.EvaluateRequest):
            raise ApplicationError("not an evaluate request", type=INVALID_REQUEST, non_retryable=True)
        outcomes = await evaluate_remote(socket_path, parsed, served_profile=profile)
        return [o.to_json() for o in outcomes]

    return evaluate


def cel_activity(evaluate: Evaluate) -> Callable[[CelInput], Awaitable[CelResult]]:
    """`cel.evaluate`: outcomes are recorded; an unavailable evaluator is retried by Temporal (3 attempts)."""

    @activity.defn(name=CEL_EVALUATE)
    async def cel_evaluate(data: CelInput) -> CelResult:
        try:
            return CelResult(await evaluate(data.request))
        except EvaluatorUnavailable as e:
            raise ApplicationError(str(e), type="evaluator_unavailable") from None

    return cel_evaluate


__all__ = [
    "CONFIG_INVALID",
    "INVALID_REQUEST",
    "OUTPUT_SCHEMA_VIOLATION",
    "SIMULATION_UNAVAILABLE",
    "UNEXPECTED_ERROR",
    "Evaluate",
    "RunStore",
    "cel_activity",
    "engine_activities",
    "remote_evaluator",
    "step_activity_for",
]
