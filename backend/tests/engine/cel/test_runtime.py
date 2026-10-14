# SPDX-License-Identifier: Apache-2.0
from collections.abc import Callable
from typing import Any

import pytest
from google.protobuf import any_pb2

from dewpoint.engine.cel import runtime
from dewpoint.engine.cel import types as T
from dewpoint.engine.cel.proto import syntax_pb2
from tests.engine.cel.support import nested_maps


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


@pytest.mark.parametrize(
    "step", [runtime.parse, lambda expr: runtime.compile_checked(expr, {})], ids=["parse", "compile_checked"]
)
def test_an_ast_deeper_than_protobuf_decodes_is_a_compile_error(step: Callable[[str], Any]) -> None:
    """The parser accepts up to 30 nested maps, but the AST the runtime hands back for 17 or more is deeper than the
    protobuf decoder's limit. Its message names the problem only: never the expression, nor the decoder's text."""
    step(nested_maps(16))
    for depth in (17, 30):
        with pytest.raises(runtime.CompileError) as e:
            step(nested_maps(depth))
        assert e.value.problems == [runtime.TOO_DEEP] and str(e.value) == runtime.TOO_DEEP
        assert e.value.__cause__ is None and e.value.__suppress_context__


@pytest.mark.parametrize(
    "payload",
    [
        b"\x0a\x05abc",  # the Any wrapper itself is cut short
        any_pb2.Any(type_url="type.googleapis.com/cel.expr.ParsedExpr", value=b"\x0a\x05ab").SerializeToString(),
    ],
    ids=["wrapper", "payload"],
)
def test_an_ast_that_doesnt_decode_is_a_compile_error(payload: bytes) -> None:
    with pytest.raises(runtime.CompileError) as e:
        runtime._unpack(payload, syntax_pb2.ParsedExpr())
    assert e.value.problems == [runtime.TOO_DEEP]
    assert e.value.__cause__ is None and e.value.__suppress_context__
