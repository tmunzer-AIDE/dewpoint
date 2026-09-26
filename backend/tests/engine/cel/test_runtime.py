# SPDX-License-Identifier: Apache-2.0
import pytest

from dewpoint.engine.cel import runtime
from dewpoint.engine.cel import types as T


def test_compile_gives_a_checked_ast_and_evaluates() -> None:
    compiled = runtime.compile_checked("x + 1", {"x": T.INT})
    assert compiled.checked.expr.WhichOneof("expr_kind") == "call_expr"
    assert runtime.evaluate(compiled, {"x": 2}) == runtime.RawResult("value", 3, "INT")


def test_compile_errors_carry_every_checker_message() -> None:
    with pytest.raises(runtime.CompileError) as e:
        runtime.compile_checked("x + 'a' + y", {"x": T.INT})
    assert e.value.problems[0].startswith("1:3: found no matching overload")
    assert any("undeclared reference to 'y'" in p for p in e.value.problems)


def test_parse_only_keeps_has_as_a_test_only_select() -> None:
    parsed = runtime.parse("has(a.b)")
    assert parsed.expr.select_expr.test_only


def test_error_values_and_aborts_are_distinguished_from_strings() -> None:
    div = runtime.compile_checked("1 / x", {"x": T.INT})
    assert runtime.evaluate(div, {"x": 0}) == runtime.RawResult("error", message="INVALID_ARGUMENT: divide by zero")
    text = runtime.compile_checked("'INVALID_ARGUMENT: x'", {})
    assert runtime.evaluate(text, {}).kind == "value"
    budget = runtime.compile_checked("l.all(a, l.all(b, true))", {"l": T.LIST})
    result = runtime.evaluate(budget, {"l": list(range(200))})
    assert result.kind == "aborted" and "Iteration budget exceeded" in result.message


def test_only_supported_signatures_are_declared() -> None:
    with pytest.raises(ValueError, match="unsupported CEL type"):
        runtime.compile_checked("x", {"x": "list(dyn)"})
