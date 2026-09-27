# SPDX-License-Identifier: Apache-2.0
"""Go/no-go proof of the typed-path encoding (spec §5.3, decision 7) against the pinned runtime.

Roots are `map<string, dyn>`; an always-available array path is also declared as a qualified identifier. These tests
pin every behaviour the classifier and binder rely on. If one fails after a runtime upgrade, the profile is not safe
to ship until the encoding is re-proved."""

from typing import Any

import pytest

from dewpoint.engine.cel import runtime
from dewpoint.engine.cel import types as T
from dewpoint.engine.cel.proto import checked_pb2

DECLS = {
    "steps": T.MAP,
    "trigger": T.MAP,
    "loops": T.MAP,
    "steps.get_devices.output.devices": T.LIST_OF_MAPS,
    "steps.get_site.output.tags": T.LIST_OF_STRINGS,
    "steps.if.output.items": T.LIST_OF_MAPS,
    "trigger.sites": T.LIST_OF_MAPS,
    "loops.outer.item.ports": T.LIST_OF_MAPS,
}
DEVICES = [{"name": "ap1"}, {"name": "ap2"}]
DATA: dict[str, Any] = {
    "steps": {"get_devices": {"output": {"devices": DEVICES}}, "get_site": {"output": {"tags": ["a", "b"]}}},
    "trigger": {"sites": [{"name": "paris"}]},
    "loops": {"outer": {"item": {"ports": [{"enabled": True}]}}},
    "steps.get_devices.output.devices": DEVICES,
    "steps.get_site.output.tags": ["a", "b"],
    "steps.if.output.items": [],
    "trigger.sites": [{"name": "paris"}],
    "loops.outer.item.ports": [{"enabled": True}],
}


def _checked(expr: str) -> checked_pb2.CheckedExpr:
    return runtime.compile_checked(expr, DECLS).checked


def _ranges(c: checked_pb2.CheckedExpr) -> list[str]:
    out: list[str] = []
    stack = [c.expr]
    while stack:
        e = stack.pop()
        kind = e.WhichOneof("expr_kind")
        if kind == "comprehension_expr":
            ce = e.comprehension_expr
            out.append(c.type_map[ce.iter_range.id].WhichOneof("type_kind"))
            stack += [ce.iter_range, ce.accu_init, ce.loop_condition, ce.loop_step, ce.result]
        elif kind == "call_expr":
            stack += list(e.call_expr.args) + ([e.call_expr.target] if e.call_expr.HasField("target") else [])
        elif kind == "select_expr":
            stack.append(e.select_expr.operand)
        elif kind == "list_expr":
            stack += list(e.list_expr.elements)
    return sorted(out)


def _idents(c: checked_pb2.CheckedExpr) -> set[str]:
    return {r.name for r in c.reference_map.values() if r.name}


def _eval(expr: str, data: dict[str, Any] | None = None) -> runtime.RawResult:
    return runtime.evaluate(runtime.compile_checked(expr, DECLS), data or DATA)


@pytest.mark.parametrize(
    "expr",
    [
        "steps.get_devices.output.devices.map(d, d.name)",
        "steps.get_site.output.tags.filter(t, t.startsWith('a'))",
        "trigger.sites.exists(s, s.name == 'paris')",
        "loops.outer.item.ports.all(p, p.enabled)",
        "steps.if.output.items.map(x, x)",  # a reserved word (not in/true/false/null) is a legal segment
        "(steps.get_devices).output.devices.map(d, d)",  # parentheses don't change the resolution
    ],
)
def test_the_longest_declared_qualified_name_types_the_range_as_a_list(expr: str) -> None:
    assert _ranges(_checked(expr)) == ["list_type"]


def test_undeclared_paths_and_index_syntax_stay_dyn() -> None:
    assert _ranges(_checked("steps.other.output.items.map(i, i)")) == ["dyn"]
    assert _ranges(_checked("steps['get_devices'].output.devices.map(d, d)")) == ["dyn"]


def test_a_nested_list_under_an_element_stays_dyn() -> None:
    assert _ranges(_checked("steps.get_devices.output.devices.map(d, d.ports.map(p, p))")) == ["dyn", "list_type"]


def test_the_checker_resolves_qualified_names_to_the_declared_identifier() -> None:
    assert "steps.get_devices.output.devices" in _idents(_checked("steps.get_devices.output.devices.size()"))
    assert _idents(_checked("steps.get_devices.output")) >= {"steps"}  # a prefix goes through the root


def test_typed_paths_catch_type_errors_at_check_time() -> None:
    with pytest.raises(runtime.CompileError, match="no matching overload"):
        _checked("steps.get_devices.output.devices + 1")


def test_has_on_the_root_and_on_prefixes_works() -> None:
    assert _eval("has(steps.get_devices)").value is True
    assert _eval("has(steps.missing)").value is False
    assert _eval("has(steps.get_devices.output)").value is True


def test_has_on_a_declared_typed_path_collapses_into_the_identifier() -> None:
    """The checker rewrites the test-only select into the identifier: the result is the list, not a bool. The
    classifier rejects this form (cel.has_on_typed_path); these assertions pin why."""
    c = _checked("has(steps.get_devices.output.devices)")
    assert c.expr.WhichOneof("expr_kind") == "ident_expr"
    assert c.type_map[c.expr.id].WhichOneof("type_kind") == "list_type"
    assert _eval("has(steps.get_devices.output.devices)").value == DEVICES
    with pytest.raises(runtime.CompileError):
        _checked("has(steps.get_devices.output.devices) && true")
    parsed = runtime.parse("has(steps.get_devices.output.devices)")
    assert parsed.expr.id == c.expr.id and parsed.expr.select_expr.test_only  # ids match: detectable


def test_binding_both_the_root_and_the_qualified_identifier() -> None:
    assert _eval("steps.get_devices.output.devices.map(d, d.name)").value == ["ap1", "ap2"]
    conflict = {**DATA, "steps.get_devices.output.devices": [{"name": "qualified"}]}
    assert _eval("steps.get_devices.output.devices.map(d, d.name)", conflict).value == ["qualified"]
    missing = {k: v for k, v in DATA.items() if not k.startswith("steps.get_devices")}
    missing["steps"] = {}
    assert _eval("has(steps.get_devices) ? steps.get_devices.output.devices.size() : 0", missing).value == 0


def test_an_iteration_variable_shadows_a_root_in_checker_and_runtime_alike() -> None:
    expr = "[{'get_devices': {'output': {'devices': {'b': 1, 'a': 2}}}}].map(steps, steps.get_devices.output.devices)"
    c = _checked(expr)
    assert "steps.get_devices.output.devices" not in _idents(c)
    assert _eval(expr).value == [{"b": 1, "a": 2}]


def test_the_runtime_checks_declared_types_deeply_at_binding() -> None:
    bad = {**DATA, "steps.get_devices.output.devices": {"b": {"name": 1}}}
    result = _eval("steps.get_devices.output.devices.map(d, d)", bad)
    assert result.kind == "error" and "Unexpected value type" in result.message


def test_loop_is_a_reserved_identifier() -> None:
    with pytest.raises(runtime.CompileError, match="reserved identifier: loop"):
        runtime.compile_checked("loop.item", {"loop": T.MAP})


@pytest.mark.parametrize("word", ["in", "true", "false", "null"])
def test_four_keywords_cannot_be_selected_as_fields(word: str) -> None:
    with pytest.raises(runtime.CompileError):
        runtime.compile_checked(f"steps.{word}.output", {"steps": T.MAP})


def test_serialization_is_not_deterministic_but_the_decoded_ast_is() -> None:
    expr = "steps.get_devices.output.devices.map(d, d.name)"
    a, b = _checked(expr), _checked(expr)
    assert a == b
    assert a.SerializeToString(deterministic=True) == b.SerializeToString(deterministic=True)


def test_many_declarations_compile_quickly() -> None:
    import time

    decls = {"steps": T.MAP, **{f"steps.s{i}.output.items": T.LIST_OF_MAPS for i in range(2000)}}
    started = time.perf_counter()
    for i in range(50):
        runtime.compile_checked(f"steps.s{i}.output.items.map(x, x.v)", decls)
    assert time.perf_counter() - started < 5.0
