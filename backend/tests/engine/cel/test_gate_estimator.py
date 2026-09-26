# SPDX-License-Identifier: Apache-2.0
"""Gate 6 (spec §5.9): estimator soundness. Random local-class expressions over the allow-list, evaluated on random
inputs within the caps: measured iterations and result sizes never exceed the stored bounds. The size model's own
bound against canonical JSON is proved here too, since the estimator relies on it."""

import json
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dewpoint.engine.canonical import canonical_json
from dewpoint.engine.cel import bind, caps, classify, runtime
from dewpoint.engine.cel import types as T

DECLS = {"l": T.LIST_OF_MAPS, "m": T.MAP, "s": T.STRING}
json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-(2**63), 2**63 - 1) | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=20),
    lambda inner: st.lists(inner, max_size=5) | st.dictionaries(st.text(max_size=5), inner, max_size=5),
    max_leaves=30,
)  # fmt: skip


@given(json_values)
def test_the_size_model_is_bounded_by_json(value: Any) -> None:
    assert caps.model_size(value) <= 8 * len(canonical_json(value)) + 8


@dataclass(frozen=True)
class Gen:
    text: str
    ranges: tuple[str, ...] = ()  # texts of every comprehension range, each evaluated once


def _join(op: str, a: Gen, b: Gen) -> Gen:
    return Gen(f"({a.text}) {op} ({b.text})", a.ranges + b.ranges)


def _comp(rng: Gen, macro: str, body: str) -> Gen:
    return Gen(f"({rng.text}).{macro}(x, {body})", (*rng.ranges, rng.text))


strings = st.sampled_from([Gen("s"), Gen("'ab'"), Gen("string(size(s))")])


def _map_lists(depth: int) -> st.SearchStrategy[Gen]:
    leaf = st.just(Gen("l"))
    if depth == 0:
        return leaf
    inner = _map_lists(depth - 1)
    return (
        leaf
        | st.builds(lambda r: _comp(r, "filter", "x.s.startsWith('a')"), inner)
        | st.builds(lambda a, b: _join("+", a, b), inner, inner)
    )


def _string_lists(depth: int) -> st.SearchStrategy[Gen]:
    leaf = st.sampled_from([Gen("sortedKeys(m)"), Gen("['a', 'b']")])
    if depth == 0:
        return leaf
    inner = _string_lists(depth - 1)
    return (
        leaf
        | st.builds(lambda r: _comp(r, "map", "x.s"), _map_lists(depth - 1))
        | st.builds(lambda r, t: _comp(r, "map", f"x + {t.text}"), inner, strings)
        | st.builds(lambda r: _comp(r, "filter", "size(x) > 1"), inner)
        | st.builds(lambda a, b: _join("+", a, b), inner, inner)
    )


DEPTH = 4  # keeps every generated expression within the parser's recursion limit of 32
expressions = (
    _map_lists(DEPTH)
    | _string_lists(DEPTH)
    | st.builds(lambda r: _comp(r, "exists", "x.s == s"), _map_lists(DEPTH - 1))
    | st.builds(lambda r: _comp(r, "map", "[x]"), _string_lists(DEPTH - 1))
    | st.builds(lambda a, b: _join("+", a, b), strings, strings)
)
inputs = st.fixed_dictionaries(
    {
        "l": st.lists(st.fixed_dictionaries({"s": st.text("ab", max_size=20)}), max_size=caps.LIST_LENGTH),
        "m": st.dictionaries(st.text("abc", min_size=1, max_size=4), st.integers(0, 9), max_size=caps.MAP_ENTRIES),
        "s": st.text("ab", max_size=caps.STRING_BYTES),
    }
)


# Within the caps, but with the most model bytes per JSON byte: many tiny values, near the total JSON cap. Random
# inputs rarely get here.
DENSE: dict[str, Any] = {
    "l": [{"s": "a", **{f"a{i:02d}": 0 for i in range(35)}} for _ in range(caps.LIST_LENGTH)],
    "m": {f"{i:03d}": 0 for i in range(caps.MAP_ENTRIES)},
    "s": "ab",
}


def _length(text: str, values: dict[str, Any]) -> int:
    got = runtime.evaluate(runtime.compile_checked(text, DECLS), values)
    return len(got.value) if got.kind == "value" else 0


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(expressions, inputs)
def test_measured_work_never_exceeds_the_stored_bounds(gen: Gen, values: dict[str, Any]) -> None:
    program = runtime.compile_checked(gen.text, DECLS)
    c = classify.classify(gen.text, program.checked)
    if c.mode != "local":
        return
    assert c.iterations is not None and c.bytes is not None
    for inputs in (values, DENSE):
        assert bind.measure(inputs).within_caps
        raw = runtime.evaluate(program, inputs)
        assert raw.kind != "aborted"  # the budget can never fire for the local class
        if raw.kind == "value":
            assert caps.model_size(raw.value) <= c.bytes
        assert sum(_length(r, inputs) for r in gen.ranges) <= c.iterations


# The worst local-class cases at the caps: single map/filter steps and chains, whose accumulators the runtime keeps
# until the evaluation ends (caps.ACCUMULATOR_SLOT).
PEAK_PROBES = [
    "sortedKeys(m).map(k, m[k])",
    "l.map(x, x.s + 'b')",
    "l.filter(x, x.s.startsWith('a')).map(x, x.s)",
    "sortedKeys(m).map(k, m[k]).filter(v, v >= 0)",
    "l.map(x, x.s) + l.map(x, x.s)",
    "l.map(x, x.s).filter(y, y != '').map(z, z + 'b')",
]
# Measured in a fresh process: forking pytest (multi-threaded once the database tests have run) risks a deadlocked
# child. The child warms the runtime on a trivial evaluation first, so only the probe's own work is measured. On
# Linux it then returns free heap pages (glibc) and restarts the high-water mark from the current RSS: otherwise an
# earlier peak, or resident pages the probe reuses, hides its growth. An empty expression is the control: `values`
# bytes, written and held.
MEASURE = textwrap.dedent(
    """
    import ctypes, json, resource, sys
    from dewpoint.engine.cel import evaluate, runtime

    def peak():
        if sys.platform == "linux":
            with open("/proc/self/status") as f:
                return next(int(line.split()[1]) * 1024 for line in f if line.startswith("VmHWM:"))
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS

    expr, decls, values = json.load(sys.stdin)
    program = runtime.compile_checked(expr, decls) if expr else None
    evaluate.run(runtime.compile_checked("1 + 1", {}), {})
    if sys.platform == "linux":
        ctypes.CDLL(None).malloc_trim(0)
        with open("/proc/self/clear_refs", "w") as f:
            f.write("5")
    before = peak()
    held = evaluate.run(program, values) if program else b"x" * values
    print(peak() - before)
    """
)


def _peak_growth(expr: str, values: dict[str, Any] | int) -> int:
    """Peak RSS growth while the probe evaluates. A child that fails fails the measurement: it never reports a growth
    it didn't measure."""
    done = subprocess.run(
        [sys.executable, "-c", MEASURE],
        input=json.dumps([expr, DECLS, values]),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0 and done.stdout.strip(), f"the measuring child failed: {done.stderr[-500:]}"
    return int(done.stdout)


def test_the_peak_memory_probes_are_local_class() -> None:
    """The memory gate below measures local-class expressions only: each probe must stay local."""
    for expr in PEAK_PROBES:
        c = classify.classify(expr, runtime.compile_checked(expr, DECLS).checked)
        assert c.mode == "local" and c.bytes is not None, (expr, c.reason, c.bytes)


def test_a_failing_measurement_child_fails_the_measurement() -> None:
    with pytest.raises(AssertionError, match="measuring child failed"):
        _peak_growth("l.map(x, ", {})  # the child can't compile it


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="only Linux resets the peak: elsewhere an earlier peak can hide part of the growth (Linux is authoritative)",
)
def test_the_measurement_sees_a_known_allocation() -> None:
    """A measurement blind to memory would pass every probe (Linux's ru_maxrss did: an earlier peak hid 1-3 MiB of
    growth). The child writes 1 MiB it holds; the measurement must see it."""
    assert _peak_growth("", 1 << 20) >= 0.9 * (1 << 20)


@pytest.mark.skipif(sys.platform not in ("linux", "darwin"), reason="needs resource.ru_maxrss")
def test_peak_memory_stays_within_one_and_a_half_times_the_bound() -> None:
    """Worst local-class expressions at the caps, each in a fresh process: peak growth stays within 1.5 x its own
    stored bound and 1.5 x the local limit. Linux (the CI gate job) is authoritative; results go to
    $DEWPOINT_CEL_GATE_RESULTS/memory.json when set, to tune ACCUMULATOR_SLOT and the caps."""
    values: dict[str, Any] = {
        "l": [{"s": "a" * 40} for _ in range(caps.LIST_LENGTH)],
        "m": {f"k{i:03d}": i for i in range(caps.MAP_ENTRIES)},
        "s": "a" * 10_000,
    }
    measured: dict[str, dict[str, int]] = {}
    for expr in PEAK_PROBES:
        c = classify.classify(expr, runtime.compile_checked(expr, DECLS).checked)
        assert c.bytes is not None
        measured[expr] = {"grown": _peak_growth(expr, values), "bound": c.bytes}
    if directory := os.environ.get("DEWPOINT_CEL_GATE_RESULTS"):
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "memory.json"), "w") as f:
            json.dump({"platform": sys.platform, "probes": measured}, f, indent=1, sort_keys=True)
    for expr, m in measured.items():
        assert m["grown"] > 0, (expr, m, "the measurement is blind: every probe keeps its accumulator copies")
        assert m["grown"] <= 1.5 * m["bound"], (expr, m)
        assert m["grown"] <= 1.5 * classify.MAX_LOCAL_BYTES, (expr, m)
