# SPDX-License-Identifier: Apache-2.0
"""One evaluation and its outcome (spec §5.7 results, §5.10 codes). Used in-process by the interpreter (local class)
and inside the evaluator's child process (activity class): both paths give the same outcome for the same input."""

import functools
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dewpoint.engine.cel import bind, canonical, runtime
from dewpoint.engine.cel.record import ExpressionRecord

# Outcome codes. Evaluation outcomes are recorded and never retried (spec §5.7).
ITERATION_BUDGET = "iteration_budget_exceeded"
TYPE_MISMATCH = "type_mismatch"
EVALUATION_ERROR = "evaluation_error"  # any other CEL runtime error: missing key, division by zero, bad argument
NON_JSON = "non_json_value"
OUTPUT_TOO_LARGE = "output_too_large"
INPUT_TOO_LARGE = "input_too_large"
MEMORY_LIMIT = "memory_limit"
CPU_LIMIT = "cpu_limit"
TIMEOUT = "timeout"
CRASHED = "evaluation_crashed"  # the child died another way (e.g. a signal from native code)
PROFILE_UNAVAILABLE = "cel_profile_unavailable"
_BINDING_ERRORS = (
    "No matching overloads found : asList(",
    "Unexpected value type for",
    "Non-CEL value type",
    "Integer value",
)


@dataclass(frozen=True)
class Outcome:
    value: Any = None
    error: str | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_json(self) -> dict[str, Any]:
        return {"ok": self.value} if self.ok else {"error": self.error, "message": self.message}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Outcome":
        if "ok" in data:
            return cls(value=data["ok"])
        return cls(error=str(data["error"]), message=str(data.get("message", "")))


@functools.lru_cache(maxsize=512)
def _compiled(expr: str, declarations: tuple[tuple[str, str], ...]) -> runtime.Compiled:
    return runtime.compile_checked(expr, dict(declarations))


def compiled(expr: str, declarations: Mapping[str, str]) -> runtime.Compiled:
    """Compile once per (text, declarations): a version's records compile identically everywhere."""
    return _compiled(expr, tuple(sorted(declarations.items())))


def _error_code(message: str) -> str:
    return TYPE_MISMATCH if any(m in message for m in _BINDING_ERRORS) else EVALUATION_ERROR


def run(program: runtime.Compiled, bindings: Mapping[str, Any]) -> Outcome:
    raw = runtime.evaluate(program, bindings)
    if raw.kind == "aborted":
        code = ITERATION_BUDGET if "Iteration budget exceeded" in raw.message else EVALUATION_ERROR
        return Outcome(error=code, message=raw.message)
    if raw.kind == "error":
        return Outcome(error=_error_code(raw.message), message=raw.message)
    try:
        return Outcome(value=canonical.to_output(raw.value))
    except canonical.NonJsonValue as e:
        return Outcome(error=NON_JSON, message=f"The result holds {e}, which JSON can't represent.")
    except canonical.OutputTooLarge as e:
        return Outcome(error=OUTPUT_TOO_LARGE, message=str(e))


def evaluate_local(record: ExpressionRecord, view: bind.ScopeView) -> Outcome:
    """The in-process path: bind, evaluate, canonicalize."""
    try:
        bindings = bind.bind(record, view)
    except bind.BindingError as e:
        return Outcome(error=TYPE_MISMATCH, message=str(e))
    return run(compiled(record.expr, record.declarations), bindings)
