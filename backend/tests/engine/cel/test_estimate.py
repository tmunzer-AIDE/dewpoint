# SPDX-License-Identifier: Apache-2.0
import pytest

from dewpoint.engine.cel import caps, estimate, runtime
from dewpoint.engine.cel import types as T

DECLS = {"trigger": T.MAP, "trigger.l": T.LIST_OF_MAPS, "m": T.MAP, "s": T.STRING}
INPUT = caps.INPUT_MODEL_BYTES
N = caps.LIST_LENGTH
RETAINED = caps.ACCUMULATOR_SLOT * N * (N + 1) // 2  # one list-building comprehension over a list at the cap


def bounds(expr: str) -> estimate.Bounds:
    return estimate.estimate(runtime.compile_checked(expr, DECLS).checked)


def test_the_size_model() -> None:
    assert caps.model_size(None) == caps.model_size(1.5) == caps.SCALAR
    assert caps.model_size("héllo") == caps.SCALAR + 6  # UTF-8 bytes
    assert caps.model_size([1, "a"]) == caps.SCALAR + caps.SCALAR + caps.SCALAR + 1
    assert caps.model_size({"a": 1}) == 3 * caps.SCALAR + 1


def test_literals_are_exact_and_inputs_are_at_the_caps() -> None:
    literal = bounds("[1, 2, 3].map(x, x * 2)")
    # the largest value (16 for the list, 16 per element), plus the 1 + 2 + 3 accumulator slots the runtime keeps
    assert (literal.iterations, literal.bytes, literal.retained) == (
        3,
        64 + 6 * caps.ACCUMULATOR_SLOT,
        6 * caps.ACCUMULATOR_SLOT,
    )
    assert bounds("trigger.x == 1").bytes == INPUT
    assert bounds("trigger.l.all(e, true)").iterations == caps.LIST_LENGTH


def test_distinct_inputs_share_the_input_mass_and_overlapping_ones_add_up() -> None:
    assert bounds("trigger.a + '-' + trigger.b").bytes < 2 * INPUT
    assert bounds("trigger.a + trigger.a").bytes > 2 * INPUT
    assert bounds("trigger.a + trigger.a.b").bytes > 2 * INPUT  # a prefix overlaps its extension


def test_list_building_comprehensions_charge_every_retained_accumulator() -> None:
    """cel-expr-python keeps each iteration's copy of a map or filter accumulator until the evaluation ends: memory
    quadratic in the range, summed over a chain (measured; tests/engine/cel/test_gate_estimator.py)."""
    assert bounds("trigger.l.map(e, e.mac)").retained == RETAINED
    assert bounds("trigger.l.filter(e, true).map(e, e.mac)").retained == 2 * RETAINED
    assert bounds("trigger.l.map(e, e.mac).filter(v, v != '').map(v, v + 'b')").retained == 3 * RETAINED
    assert bounds("trigger.l.exists(e, e.mac == 'x') && trigger.l.all(e, true)").retained == 0  # booleans keep none


def test_comprehension_values_are_affine_in_the_element() -> None:
    assert bounds("trigger.l.map(e, e.mac)").bytes <= INPUT + caps.SCALAR * 2 + RETAINED
    assert bounds("trigger.l.filter(e, e.x == trigger.site)").bytes <= INPUT + caps.SCALAR * 2 + RETAINED
    assert bounds("trigger.l.map(e, e.mac + trigger.suffix)").bytes > 100 * INPUT  # copies an input per element


def test_values_by_key_over_sorted_keys_sum_to_the_map() -> None:
    assert bounds("sortedKeys(m).map(k, m[k])").bytes <= INPUT + caps.SCALAR * 2 + RETAINED
    assert bounds("sortedKeys(m).map(k, m['a'])").bytes > 100 * INPUT  # the same key every time


def test_work_counts_python_calls_per_iteration() -> None:
    native = bounds("trigger.l.exists(e, e.mac == 'x')").work
    called = bounds("trigger.l.exists(e, macOui(e.mac) == 'x')").work
    assert called - native == caps.LIST_LENGTH * (estimate.FN_WORK + 1)  # the call node itself counts one too


def test_regex_work_follows_the_text_it_scans() -> None:
    small = bounds("'abc'.matches('^a')").work
    big = bounds("s.matches('^a')").work
    assert big - small >= (caps.STRING_BYTES) // estimate.REGEX_BYTES_PER_WORK


@pytest.mark.parametrize(
    ("expr", "reason"),
    [
        ("trigger.l.map(e, trigger.l.map(f, f))", "more than one nested loop"),
        ("s.matches(trigger.p)", "a regular expression that isn't a short literal"),
        ("timestamp(trigger.t).getHours('Europe/Paris')", "a named time zone (only UTC and fixed offsets run inline)"),
        ("timestamp(trigger.t).getHours(trigger.zone)", "a named time zone (only UTC and fixed offsets run inline)"),
    ],
)
def test_outside_the_allow_list(expr: str, reason: str) -> None:
    with pytest.raises(estimate.NotLocal) as e:
        bounds(expr)
    assert e.value.reason == reason


def test_fixed_zones_are_allowed() -> None:
    assert bounds("timestamp(trigger.t).getHours('UTC') + timestamp(trigger.t).getHours('-05:30')").iterations == 0
