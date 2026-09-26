# SPDX-License-Identifier: Apache-2.0
from typing import Any

import pytest

from dewpoint.engine.cel import functions as F
from dewpoint.engine.cel import runtime
from dewpoint.engine.cel import types as T


def run(expr: str, **values: Any) -> runtime.RawResult:
    return runtime.evaluate(runtime.compile_checked(expr, {k: T.DYN for k in values}), values)


def test_sorted_keys_orders_by_code_point() -> None:
    assert run("sortedKeys(m)", m={"b": 1, "a": 2, "B": 3, "é": 4}).value == ["B", "a", "b", "é"]


def test_as_list_accepts_only_lists() -> None:
    assert run("asList(x).map(i, i * 2)", x=[1, 2]).value == [2, 4]
    for bad in ({"a": 1}, "ab", 1, None):
        assert run("asList(x)", x=bad).kind == "error"


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("ipInCidr('10.1.2.3', '10.0.0.0/8')", True),
        ("ipInCidr('11.1.2.3', '10.0.0.0/8')", False),
        ("ipInCidr('2001:db8::1', '2001:db8::/32')", True),
        ("ipInCidr('10.1.2.3', '2001:db8::/32')", False),
        ("cidrContains('10.0.0.0/8', '10.1.0.0/16')", True),
        ("cidrContains('10.1.0.0/16', '10.0.0.0/8')", False),
        ("cidrContains('10.0.0.0/8', '10.1.2.3')", True),
        ("macNormalize('5C:5B:35:00:00:01')", "5c5b35000001"),
        ("macNormalize('5c-5b-35-00-00-01')", "5c5b35000001"),
        ("macNormalize('5c5b.3500.0001')", "5c5b35000001"),
        ("macOui('5C5B35000001')", "5c5b35"),
    ],
)
def test_network_and_mac_functions(expr: str, expected: Any) -> None:
    assert run(expr).value == expected


@pytest.mark.parametrize(
    "expr",
    [
        "ipInCidr('nope', '10.0.0.0/8')",
        "cidrContains('10.0.0.0/33', '10.0.0.1')",
        "macNormalize('5c:5b')",
        "macOui('')",
    ],
)
def test_bad_arguments_are_errors_that_logic_can_absorb(expr: str) -> None:
    assert run(expr).kind == "error"
    assert run(f"{expr} == {expr} || true").value is True


def test_hostile_argument_lengths_are_refused_before_parsing() -> None:
    assert run("macNormalize(s)", s="a" * 10_000).kind == "error"
    assert run("ipInCidr(s, '10.0.0.0/8')", s="1" * 10_000).kind == "error"


def test_every_function_declares_its_metadata() -> None:
    for f in F.FUNCTIONS:
        assert f.deterministic and f.cost in ("constant", "n log n") and f.output
        assert f.takes_map == (f.name == "sortedKeys")


def test_fn1_functions_are_registered() -> None:
    compiled = runtime.compile_checked("sortedKeys(m)", {"m": T.MAP})
    assert runtime.evaluate(compiled, {"m": {"b": 1, "a": 2}}).value == ["a", "b"]
