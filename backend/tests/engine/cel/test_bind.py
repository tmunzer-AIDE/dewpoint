# SPDX-License-Identifier: Apache-2.0
from typing import Any

import pytest

from dewpoint.engine.cel import bind, caps
from dewpoint.engine.cel import types as T
from dewpoint.engine.cel.record import Projection
from tests.engine.cel.support import make_record


def view(**overrides: Any) -> bind.ScopeView:
    base: dict[str, Any] = {
        "trigger": {"site": {"id": "s1", "name": "Paris", "big": "x" * 1000}, "events": [{"mac": "a"}]},
        "steps": {"a": {"output": {"n": 1, "devices": [{"name": "ap1"}]}}, "b": {}},
        "vars": {"limit": 3},
        "loops": {},
        "run": {"id": "r1", "started_at": "2026-09-26T00:00:00Z", "now": "2026-09-26T00:00:01Z"},
    }
    return bind.ScopeView(**{**base, **overrides})


def test_roots_are_projected_to_what_the_expression_reads() -> None:
    r = make_record("trigger.site.id == 'x' && has(trigger.site.name) && has(steps.b.output)")
    got = bind.bind(r, view())
    assert got == {"trigger": {"site": {"id": "s1", "name": None}}, "steps": {"b": {}}}


def test_a_bare_root_is_bound_whole() -> None:
    r = make_record("size(vars) > 0")
    assert bind.bind(r, view())["vars"] == {"limit": 3}


def test_non_maps_are_kept_whole_so_errors_match() -> None:
    assert bind.project([1, 2], [Projection(("x", "a"), False)]) == [1, 2]
    assert bind.project({"a": [1, 2]}, [Projection(("x", "a", "b"), False)]) == {"a": [1, 2]}


def test_typed_paths_are_bound_and_checked() -> None:
    r = make_record("steps.a.output.devices.map(d, d.name)", {"steps.a.output.devices": T.LIST_OF_MAPS})
    assert bind.bind(r, view()) == {"steps.a.output.devices": [{"name": "ap1"}]}
    broken = view(steps={"a": {"output": {"devices": {"name": "ap1"}}}})
    with pytest.raises(bind.BindingError, match="declared type"):
        bind.bind(r, broken)
    with pytest.raises(bind.BindingError, match="missing"):
        bind.bind(r, view(steps={"a": {}}))


def test_item_and_index_are_bound_inside_loops() -> None:
    r = make_record("item.mac + string(index)", item=True)
    assert bind.bind(r, view(item={"mac": "m", "x": 1}, index=2)) == {"item": {"mac": "m"}, "index": 2}


@pytest.mark.parametrize("bad", [2**63, -(2**63) - 1, float("inf"), b"x", {1: "a"}])
def test_values_must_be_plain_json_the_runtime_can_hold(bad: Any) -> None:
    r = make_record("vars.x == 1")
    with pytest.raises(bind.BindingError):
        bind.bind(r, view(vars={"x": bad}))


def test_measure_against_the_caps() -> None:
    m = bind.measure({"a": [1] * caps.LIST_LENGTH, "b": "x" * 10})
    assert m.within_caps and m.longest_list == caps.LIST_LENGTH and m.longest_string == 10
    assert not bind.measure({"a": [1] * (caps.LIST_LENGTH + 1)}).within_caps
    assert not bind.measure({"a": {str(i): i for i in range(caps.MAP_ENTRIES + 1)}}).within_caps
    assert not bind.measure({"a": "x" * (caps.STRING_BYTES + 1)}).within_caps
    assert not bind.measure({"a": "x" * 40_000, "b": "y" * 40_000}).within_caps  # total over 64 KiB
