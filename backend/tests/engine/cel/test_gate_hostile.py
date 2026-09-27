# SPDX-License-Identifier: Apache-2.0
"""Gate 2 (spec §5.9), in-process half: hostile expressions end in a compile error, a value or an error, never a
crash or a hang. The activity-class half runs in the evaluator's child (tests/apps/cel_evaluator)."""

from typing import Any

import pytest

from dewpoint.engine.cel import caps, classify, evaluate, runtime
from dewpoint.engine.cel import types as T

COMPILE_BOMBS = {
    "nest_paren_1e3": "(" * 1_000 + "1" + ")" * 1_000,
    "nest_paren_1e4": "(" * 10_000 + "1" + ")" * 10_000,
    "nest_paren_1e5": "(" * 100_000 + "1" + ")" * 100_000,
    "not_chain_1e5": "!" * 100_000 + "true",
    "add_chain_1e4": "1" + " + 1" * 10_000,
    "add_chain_1e5": "1" + " + 1" * 100_000,
    "list_1e5": "[" + ",".join(["1"] * 100_000) + "]",
    "select_chain_1e3": "x" + ".a" * 1_000,
}
AT_CAPS: dict[str, Any] = {
    "l": [{"s": "a" * 40} for _ in range(caps.LIST_LENGTH)],
    "m": {f"k{i:03d}": i for i in range(caps.MAP_ENTRIES)},
    "s": "a" * 10_000 + "!",
}
DECLS = {"l": T.LIST_OF_MAPS, "m": T.MAP, "s": T.STRING, "x": T.DYN}
LOCAL_PROBES = [
    "l.map(x, x.s + 'b').size()",
    "sortedKeys(m).map(k, m[k]).size()",
    "l.filter(x, x.s.matches('^(a+)+$')).size()",
    "s.matches('(a+)+$')",
    "l.exists(x, x.s == s) || l.all(x, size(x.s) > 0)",
    "s + s + s",
    "[s, s, s, s].size()",
]


@pytest.mark.parametrize("name", sorted(COMPILE_BOMBS))
def test_compile_bombs_are_compile_errors(name: str) -> None:
    for step in (lambda e: runtime.parse(e), lambda e: runtime.compile_checked(e, DECLS)):
        with pytest.raises(runtime.CompileError):
            step(COMPILE_BOMBS[name])


@pytest.mark.parametrize("expr", LOCAL_PROBES)
def test_local_class_probes_end_in_a_value_or_an_error(expr: str) -> None:
    program = runtime.compile_checked(expr, DECLS)
    assert classify.classify(expr, program.checked).mode == "local", expr
    outcome = evaluate.run(program, {k: AT_CAPS[k] for k in ("l", "m", "s")})
    assert outcome.ok or outcome.error in (evaluate.EVALUATION_ERROR, evaluate.OUTPUT_TOO_LARGE), outcome
