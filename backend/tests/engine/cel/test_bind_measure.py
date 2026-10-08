# SPDX-License-Identifier: Apache-2.0
"""#18: measuring a view's bindings costs what routing needs, never a value's every byte. Past a local cap a value is
known to be past it from a walk that serializes nothing; within the caps the measure is exact, as before. Routing,
the nodes the yield budget charges and the handles seen stay what they were, so no workflow command changes."""

from typing import Any

import pytest

from dewpoint.engine.canonical import canonical_json
from dewpoint.engine.cel import bind, caps
from dewpoint.engine.cel.bind import Measure
from dewpoint.engine.handles import MARKER

S = caps.STRING_BYTES


def before(bindings: dict[str, Any]) -> Measure:
    """`measure` as it was: every value serialized in full."""
    sizes = [len(canonical_json(v)) for v in bindings.values()]
    lists = maps = strings = nodes = 0
    handles = False
    stack = list(bindings.values())
    while stack:
        v = stack.pop()
        nodes += 1
        if isinstance(v, dict):
            maps = max(maps, len(v))
            handles = handles or MARKER in v
            stack.extend(v.values())
        elif isinstance(v, list):
            lists = max(lists, len(v))
            stack.extend(v)
        elif isinstance(v, str):
            strings = max(strings, len(v.encode()))
    return Measure(sum(sizes), max(sizes, default=0), lists, maps, strings, nodes, handles)


CORPUS: dict[str, dict[str, Any]] = {
    "empty": {},
    "scalars": {"a": 1, "b": 2.5, "c": True, "d": None, "e": "x"},
    "string at the cap": {"s": "x" * S},
    "string past the cap": {"s": "x" * (S + 1)},
    "multibyte at the cap's bytes": {"s": "é" * (S // 2)},
    "multibyte past the cap's bytes": {"s": "é" * (S // 2 + 1)},
    "escapes": {"s": "\u0001" * 5_000, "t": '"' * 5_000},
    "escapes past the total": {"s": ["\u0001" * 10_000, "\u0001" * 10_000]},
    "list at the cap": {"l": list(range(caps.LIST_LENGTH))},
    "list past the cap": {"l": list(range(caps.LIST_LENGTH + 1))},
    "map at the cap": {"m": {f"k{i}": i for i in range(caps.MAP_ENTRIES)}},
    "map past the cap": {"m": {f"k{i}": i for i in range(caps.MAP_ENTRIES + 1)}},
    "total just within": {"a": "x" * 16_000, "b": "y" * 16_000, "c": "z" * 16_000, "d": "w" * 16_000},
    "total just past": {"a": ["x" * 16_000, "y" * 16_000], "b": ["z" * 16_000, "w" * 16_000, "v" * 2_000]},
    "nested": {"n": [{"k": [1, {"j": "x" * 100}]}, [[[]]], {}]},
    "a handle": {"h": {MARKER: "claim", "id": "c1"}},
    "huge string": {"s": "x" * 1_800_000},
    "many strings": {"l": ["x" * 10_000 for _ in range(1_000)]},
}


@pytest.mark.parametrize("name", list(CORPUS))
def test_routing_nodes_and_handles_stay_what_they_were(name: str) -> None:
    """What reaches a workflow command (the route, the yield budget's nodes, a handle seen) is unchanged; within the
    caps every field is exact, as before."""
    now, was = bind.measure(CORPUS[name]), before(CORPUS[name])
    assert (now.within_caps, now.nodes, now.handles) == (was.within_caps, was.nodes, was.handles)
    if was.within_caps:
        assert now == was


ESCAPED = {"escapes past the total"}  # within the caps by its characters, past them only once escaped


@pytest.mark.parametrize("name", [n for n in CORPUS if not before(CORPUS[n]).within_caps and n not in ESCAPED])
def test_a_value_past_a_cap_is_never_serialized(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """#18: each view's measure serialized every value it bound, a 1.8 MiB string once per item. Past a cap by its
    lengths (its characters, its elements, its entries), nothing is serialized."""

    def serialized(_value: Any) -> bytes:
        raise AssertionError("serialized past a cap")

    monkeypatch.setattr(bind, "canonical_json", serialized)
    assert not bind.measure(CORPUS[name]).within_caps


@pytest.mark.parametrize("name", list(CORPUS))
def test_what_a_measure_serializes_is_bounded_by_the_caps(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only bindings within every cap by their lengths are serialized: at most TOTAL_JSON characters, so at most six
    bytes each once escaped (a control character's `\\u0001`), whatever the values' size."""
    out: list[int] = []

    def counted(value: Any) -> bytes:
        out.append(len(encoded := canonical_json(value)))
        return encoded

    monkeypatch.setattr(bind, "canonical_json", counted)
    bind.measure(CORPUS[name])
    assert sum(out) <= 6 * caps.TOTAL_JSON
