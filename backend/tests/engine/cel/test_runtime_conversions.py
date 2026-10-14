# SPDX-License-Identifier: Apache-2.0
"""What the patched runtime (deploy/cel-runtime) changed beside the leak, and what it must not change: null values
through the paths whose ownership it fixed, a callback's exception message, conversions that fail, and values our
functions return, used after the call. The library is used directly where our functions can't reach a path."""

import gc
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from cel_expr_python import cel

from dewpoint.engine.cel import functions, runtime
from dewpoint.engine.cel import types as T

S = cel.Type.STRING
TIMES = 2000


def library_expr(
    expr: str, impl: Callable[..., Any], params: list[Any], variables: dict[str, Any] | None = None
) -> Any:
    decl = cel.FunctionDecl("f", [cel.Overload("f_o", S, params, impl=impl)])
    return cel.NewEnv(variables=variables or {}, functions=[decl]).compile(expr)


def test_a_null_argument_reaches_the_function_as_none() -> None:
    seen: list[Any] = []
    expr = library_expr("f(null)", lambda x: seen.append(x) or "ok", [cel.Type.NULL])  # a dyn overload isn't matched
    for _ in range(TIMES):
        assert expr.eval().plain_value() == "ok"
    assert seen == [None] * TIMES


def test_null_map_values_and_list_elements_reach_our_functions() -> None:
    program = runtime.compile_checked("sortedKeys(m) == ['a', 'b'] && size(asList(l)) == 3", {"m": T.MAP, "l": T.LIST})
    for _ in range(TIMES):
        assert runtime.evaluate(program, {"m": {"a": None, "b": 1}, "l": [None, 1, None]}) == runtime.RawResult(
            "value", True, "BOOL"
        )


def test_null_elements_come_back_from_our_functions() -> None:
    program = runtime.compile_checked("asList(l)", {"l": T.LIST})
    for _ in range(TIMES):
        assert runtime.evaluate(program, {"l": [None, "x", None]}).value == [None, "x", None]


# A child under the debug allocator (-X dev), which overwrites freed memory: 0.1.3 read the message after releasing
# the string that held it, which a plain run hides. One line per evaluation.
CALLBACK_ERRORS = """
from cel_expr_python import cel
S = cel.Type.STRING
for make in (lambda: ValueError("plain message"), lambda: KeyError("abc-key"), lambda: ValueError("two", 3),
             lambda: ValueError(12345)):
    def boom(_, make=make):
        raise make()
    decl = cel.FunctionDecl("f", [cel.Overload("f_o", S, [S], impl=boom)])
    expr = cel.NewEnv(variables={"m": S}, functions=[decl]).compile("f(m)")
    for _ in range(50):
        value = expr.eval(data={"m": "x"})
        try:
            print(value.plain_value())
        except Exception as e:
            print("unconvertible:", type(e).__name__)
"""


def test_a_callbacks_exception_keeps_its_exact_message() -> None:
    done = subprocess.run(
        [sys.executable, "-X", "dev", "-c", CALLBACK_ERRORS], capture_output=True, text=True, check=True, timeout=120
    )
    assert set(done.stdout.splitlines()) == {
        "OUT_OF_RANGE: plain message",
        "UNKNOWN: 'abc-key'",
        "OUT_OF_RANGE: ('two', 3)",
        "OUT_OF_RANGE: 12345",
    }


def test_our_functions_errors_keep_their_message() -> None:
    program = runtime.compile_checked("macOui(s)", {"s": T.STRING})
    for _ in range(200):
        assert runtime.evaluate(program, {"s": "not a mac address"}) == runtime.RawResult(
            "error", message="OUT_OF_RANGE: invalid_argument: macNormalize: not a MAC address"
        )  # macOui reports through macNormalize, which it calls


def test_no_matching_overload_does_not_call_the_function() -> None:
    calls: list[Any] = []
    expr = library_expr("f(m)", lambda x: calls.append(x) or "ok", [S], {"m": cel.Type.DYN})
    for _ in range(200):
        assert expr.eval(data={"m": 1}).type().name() == "ERROR"
    assert calls == []


def test_an_error_argument_does_not_call_the_function() -> None:
    calls: list[Any] = []
    expr = library_expr("f(string(1 / n))", lambda x: calls.append(x) or "ok", [S], {"n": cel.Type.INT})
    for _ in range(200):
        assert expr.eval(data={"n": 0}).type().name() == "ERROR"
    assert calls == []


def test_a_wrong_result_type_is_an_error() -> None:
    value = library_expr("f(m)", lambda _: 12345, [S], {"m": S}).eval(data={"m": "x"})
    assert value.type().name() == "ERROR"
    assert "Unexpected value type" in value.plain_value()


def test_returned_values_stay_valid_after_the_call() -> None:
    program = runtime.compile_checked(
        "sortedKeys(m)[0] + '/' + macNormalize(s) + '/' + string(size(asList(l)))",
        {"m": T.MAP, "s": T.STRING, "l": T.LIST},
    )
    expected = f"aa/{functions.mac_normalize('00-1A-2B-3C-4D-5E')}/2"
    for i in range(TIMES):
        result = runtime.evaluate(program, {"m": {"zz": 1, "aa": 2}, "s": "00-1A-2B-3C-4D-5E", "l": ["x", "y"]})
        if i % 100 == 0:
            gc.collect()
        assert result.value == expected
