# SPDX-License-Identifier: Apache-2.0
"""Publish-time classification (spec §5.5): reject, local or activity. Pure over the checked AST.

`order_problems` is the reject rule that doesn't need the workflow's schemas; the evaluator re-checks it before
evaluating anything (defence in depth)."""

from dataclasses import dataclass
from typing import Literal

from dewpoint.engine.cel import ast, estimate
from dewpoint.engine.cel.proto import checked_pb2

MAX_LOCAL_CODE_POINTS = 4_096
MAX_LOCAL_ITERATIONS = 9_999  # the runtime's budget of 10,000 lets 9,999 pass (tests/engine/cel/test_runtime.py)
MAX_LOCAL_BYTES = 4 * 1_048_576  # the largest value plus retained accumulators (estimate.py); measured by gate 6
MAX_LOCAL_WORK = 2_000_000  # roughly 0.2 s of CPU at the rate gate 7 measured; tuned from its results


@dataclass(frozen=True)
class Problem:
    code: str
    message: str
    fix: str | None = None


@dataclass(frozen=True)
class Classification:
    mode: Literal["local", "activity"]
    reason: str | None = None  # why it runs as a separate step
    iterations: int | None = None  # static bounds, when the estimator could compute them
    bytes: int | None = None
    work: int | None = None


def order_problems(checked: checked_pb2.CheckedExpr) -> list[Problem]:
    """Every comprehension whose range isn't proven a list (spec §5.5: map order would leak)."""
    found: dict[str, Problem] = {}
    for e in ast.walk(checked.expr):
        if e.WhichOneof("expr_kind") != "comprehension_expr":
            continue
        kind = ast.type_kind(checked, e.comprehension_expr.iter_range.id)
        if kind == "list_type":
            continue
        if kind == "map_type":
            found.setdefault(
                "cel.map_iteration",
                Problem(
                    "cel.map_iteration",
                    "Iterates over a map, so the order isn't guaranteed.",
                    "Use `sortedKeys(m).map(k, …)`.",
                ),
            )
        else:
            found.setdefault(
                "cel.unproven_list",
                Problem(
                    "cel.unproven_list",
                    "The type of this value is unknown, so it can't be iterated.",
                    "Wrap it: `asList(x)`.",
                ),
            )
    return [found[k] for k in sorted(found)]


def classify(expr: str, checked: checked_pb2.CheckedExpr) -> Classification:
    """For an expression that has no reject problems."""
    if len(expr) > MAX_LOCAL_CODE_POINTS:
        return Classification("activity", f"longer than {MAX_LOCAL_CODE_POINTS:,} characters")
    if ast.comprehension_depth(checked.expr) > 1:
        return Classification("activity", "more than one nested loop")
    try:
        bounds = estimate.estimate(checked)
    except estimate.NotLocal as e:
        return Classification("activity", e.reason)
    facts = (bounds.iterations, bounds.bytes, bounds.work)
    if bounds.iterations > MAX_LOCAL_ITERATIONS:
        return Classification("activity", "may iterate 10,000 times or more with large inputs", *facts)
    if bounds.bytes > MAX_LOCAL_BYTES:
        return Classification("activity", "may need more than 4 MiB of memory", *facts)
    if bounds.work > MAX_LOCAL_WORK:
        return Classification("activity", "does too much work per item to run inline", *facts)
    return Classification("local", None, *facts)
