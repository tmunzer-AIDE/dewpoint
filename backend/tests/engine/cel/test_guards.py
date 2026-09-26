# SPDX-License-Identifier: Apache-2.0
import pytest

from dewpoint.engine.cel import ast, guards, runtime
from dewpoint.engine.cel import types as T

NEED = ("steps", "a", "output")


def _guarded(expr: str) -> bool:
    """Whether every chain through steps.a.output has that path among its facts."""
    checked = runtime.compile_checked(expr, {"steps": T.MAP, "trigger": T.MAP}).checked
    facts = guards.facts_at(checked.expr)
    uses = [c for c in ast.chains(checked.expr) if (c.path[:-1] if c.presence else c.path)[:3] == NEED]
    uses = [c for c in uses if len(c.path[:-1] if c.presence else c.path) >= 3]
    assert uses, "the expression must use steps.a.output"
    return all(NEED in facts[c.expr_id] for c in uses)


@pytest.mark.parametrize(
    "expr",
    [
        "has(steps.a.output) && steps.a.output.x > 1",
        "steps.a.output.x > 1 && has(steps.a.output)",  # && absorbs the error when the guard is false
        "!has(steps.a.output) || steps.a.output.x > 1",
        "steps.a.output.x > 1 || !has(steps.a.output)",
        "has(steps.a.output) ? steps.a.output.x : 0",
        "!has(steps.a.output) ? 0 : steps.a.output.x",
        "has(steps.a.output.x) && steps.a.output.x > 1 && has(steps.a.output)",
        "has(steps.a.output) && trigger.l.exists(i, i == steps.a.output.x)",
        "has(steps.a.output) && has(steps.a.output.x)",  # the second has() reads steps.a.output
    ],
)
def test_guarded(expr: str) -> None:
    assert _guarded(expr)


@pytest.mark.parametrize(
    "expr",
    [
        "steps.a.output.x > 1",
        "has(steps.a.output.x)",  # reads steps.a.output, which may be missing
        "has(steps.a) && steps.a.output.x > 1",  # the step's entry exists even when it has no output
        "has(steps.a.output) || steps.a.output.x > 1",
        "(has(steps.a.output) ? 1 : steps.a.output.x) > 0",
        "steps.a.output.x > 1 ? has(steps.a.output) : false",  # a condition isn't guarded by its branches
        "trigger.l.exists(steps, has(steps.a.output)) && steps.a.output.x > 1",  # a shadowed root proves nothing
    ],
)
def test_unguarded(expr: str) -> None:
    assert not _guarded(expr)
