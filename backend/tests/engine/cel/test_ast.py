# SPDX-License-Identifier: Apache-2.0
from dewpoint.engine.cel import ast, runtime
from dewpoint.engine.cel import types as T

ROOTS = {"steps": T.MAP, "trigger": T.MAP, "vars": T.MAP}


def _checked(expr: str, extra: dict[str, str] | None = None) -> runtime.Compiled:
    return runtime.compile_checked(expr, {**ROOTS, **(extra or {})})


def _paths(expr: str, extra: dict[str, str] | None = None) -> list[tuple[tuple[str, ...], bool]]:
    return [(c.path, c.presence) for c in ast.chains(_checked(expr, extra).checked.expr)]


def test_chains_are_maximal_and_in_evaluation_order() -> None:
    assert _paths("steps.a.output.x + trigger.b") == [(("steps", "a", "output", "x"), False), (("trigger", "b"), False)]


def test_presence_tests_report_the_tested_field() -> None:
    assert _paths("has(steps.a.output) && steps.a.output.x > 1") == [
        (("steps", "a", "output"), True),
        (("steps", "a", "output", "x"), False),
    ]


def test_typed_identifiers_split_back_into_chains() -> None:
    extra = {"steps.a.output.devices": T.LIST_OF_MAPS}
    assert _paths("steps.a.output.devices.map(d, d.name)", extra) == [(("steps", "a", "output", "devices"), False)]


def test_index_ends_a_chain_and_call_results_are_not_chains() -> None:
    assert _paths("steps.a.output.l[0].name") == [(("steps", "a", "output", "l"), False)]
    assert _paths("sortedKeys(vars.m).size()") == [(("vars", "m"), False)]


def test_comprehension_variables_shadow_globals() -> None:
    expr = "trigger.items.map(steps, steps.x) + [vars.y]"
    assert _paths(expr) == [(("trigger", "items"), False), (("vars", "y"), False)]
    assert ast.global_idents(_checked(expr).checked.expr) == ["trigger", "vars"]


def test_comprehension_depth_counts_only_nesting_that_multiplies() -> None:
    def depth(expr: str) -> int:
        return ast.comprehension_depth(_checked(expr).checked.expr)

    assert depth("1 + 2") == 0
    assert depth("[1, 2].map(x, x)") == 1
    assert depth("[1, 2].map(x, x).filter(y, y > 1)") == 1  # the inner one is the range: it runs once
    assert depth("[[1]].map(x, x.map(y, y))") == 2


def test_result_json_types() -> None:
    def types(expr: str) -> frozenset[str] | None:
        c = _checked(expr).checked
        return ast.json_types(c.type_map[c.expr.id])

    assert types("1") == {"integer"} and types("1u") == {"integer"} and types("1.5") == {"number"}
    assert types("'a'") == {"string"} and types("true") == {"boolean"} and types("null") == {"null"}
    assert types("[1]") == {"array"} and types("{'a': 1}") == {"object"}
    assert types("timestamp('2024-01-01T00:00:00Z')") == {"string"}
    assert types("trigger.x") is None
    assert types("b'a'") == ast.NON_JSON and types("type(1)") == ast.NON_JSON
