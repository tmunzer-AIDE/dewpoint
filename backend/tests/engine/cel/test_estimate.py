# SPDX-License-Identifier: Apache-2.0
import pytest

from dewpoint.engine.cel import caps, estimate, runtime
from dewpoint.engine.cel import types as T

DECLS = {"trigger": T.MAP, "trigger.l": T.LIST_OF_MAPS, "m": T.MAP, "s": T.STRING}
INPUT = caps.INPUT_MODEL_BYTES
N = caps.LIST_LENGTH
RETAINED = caps.ACCUMULATOR_SLOT * N * (N + 1) // 2  # one list-building comprehension over a list at the cap
TEXT = caps.SCALAR + caps.STRING_BYTES  # a string input at the cap
W, V = estimate.TEXT_BYTES_PER_WORK, estimate.VALUE_BYTES_PER_WORK


def bounds(expr: str) -> estimate.Bounds:
    return estimate.estimate(runtime.compile_checked(expr, DECLS).checked)


def work(expr: str) -> int:
    return bounds(expr).work


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


def test_the_slot_covers_what_linux_measured() -> None:
    """Gate 6 on Linux (CI, checkpoint 3): a single map step at the cap grew about 52 bytes per retained slot, fixed
    overhead included. The slot charge must cover it on its own, not only through the bound's other terms."""
    assert caps.ACCUMULATOR_SLOT >= 52


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


def test_work_counts_python_calls_per_iteration_and_the_text_they_convert() -> None:
    native = work("trigger.l.exists(e, e.mac == 'x')")
    called = work("trigger.l.exists(e, macOui(e.mac) == 'x')")
    # the call node itself counts one too; the items' text crosses into Python once over the whole range
    assert called - native == N * (estimate.FN_WORK + 1) + caps.TOTAL_JSON // W


def test_python_functions_charge_converting_values() -> None:
    """sortedKeys converts the whole map, values included, node by node."""
    assert work("sortedKeys(m)") == 2 + estimate.FN_WORK + estimate.COUNT + INPUT // V


def test_text_operations_charge_the_bytes_they_copy_or_read() -> None:
    """Concatenation, size (code points), conversions, comparisons and prefixes read every byte of their operands."""
    assert work("size(s + s) == 0") - work("size('a' + 'a') == 0") == 2 * (2 * TEXT // W)
    assert work("s.startsWith(s) || s < s") - work("'a'.startsWith('a') || 'a' < 'a'") == 2 * (2 * TEXT // W)
    assert work("size(bytes(s)) == 0") - work("size(bytes('a')) == 0") == TEXT // W
    assert work("m[s] == 1") - work("m['a'] == 1") == TEXT // W  # the key is hashed


def test_text_from_the_inputs_is_at_most_a_string_at_the_cap() -> None:
    """A dynamic input used as text holds at most STRING_BYTES, whatever mass it could have as a list or map."""
    assert work("size(trigger.a + trigger.b) == 0") == work("size(s + s) == 0")
    assert work("trigger.a.matches('^a')") == work("s.matches('^a')")


def test_text_read_per_item_repeats_and_the_items_own_text_sums_to_the_json() -> None:
    per_item = work("trigger.l.exists(e, size(s) == 0)") - work("trigger.l.exists(e, size('a') == 0)")
    assert per_item == N * TEXT // W - N * (caps.SCALAR + 1) // W
    own = work("trigger.l.exists(e, size(e.name) == 0)") - work("trigger.l.exists(e, size(e) == 0)")
    assert own == N + caps.TOTAL_JSON // W  # one more node per item; the items' text is at most the list's JSON


def test_substring_search_charges_text_times_needle() -> None:
    """`contains` may compare every needle byte at every text position; a short needle costs one pass."""
    assert work("s.contains(s)") - work("'a'.contains('a')") == TEXT * TEXT // estimate.SEARCH_PAIRS_PER_WORK
    assert work("s.contains('ab')") - work("'a'.contains('ab')") == TEXT // W


def test_equality_walks_the_smaller_value() -> None:
    """Lists and maps compare node by node, and stop at the smaller one."""
    assert work("trigger.a == trigger.b") - work("1 == 2") == INPUT // V - caps.SCALAR // V
    assert work("trigger.a == 'x'") == work("1 == 2")
    # a list is searched element by element; a map only hashes the key
    assert work("trigger.k in trigger.l") - work("trigger.k in m") == INPUT // V - TEXT // W


def test_regex_work_follows_the_text_times_the_pattern() -> None:
    """RE2's cost per text byte grows with the pattern it compiles."""
    points = estimate.REGEX_BYTE_POINTS_PER_WORK
    assert work("s.matches('^abcd')") - work("s.matches('^a')") == TEXT * 5 // points - TEXT * 2 // points
    assert work("'abc'.matches('^a')") < work("s.matches('^a')")


@pytest.mark.parametrize(
    ("pattern", "written_out"),
    [
        ("[0-9]{6}", 5 * 6 + 3),  # the class, six times, and the count's own text
        ("^5c5b35[0-9a-f]{6}$", 1 + 6 + 8 * 6 + 3 + 1),
        ("(a{2,3}){4,}", ((1 * 3 + 5) + 2) * 5 + 4),  # {4,}: four copies and a star
        ("[[:alpha:]]{3}", 11 * 3 + 3),
        ("[]{]{2}", 4 * 2 + 3),  # a leading ] is literal
        ("\\d{3}x", 2 * 3 + 3 + 1),
        ("(ab", 3),  # unclosed: RE2 refuses it, but it still counts in full
    ],
)
def test_regex_counts_are_charged_as_written_out(pattern: str, written_out: int) -> None:
    assert estimate._regex_points(pattern) == written_out


def test_regex_work_uses_the_written_out_pattern() -> None:
    points = estimate.REGEX_BYTE_POINTS_PER_WORK
    assert work("s.matches('[0-9]{6}')") - work("s.matches('[0-9]')") == TEXT * 33 // points - TEXT * 5 // points


@pytest.mark.parametrize(
    ("expr", "reason"),
    [
        ("trigger.l.map(e, trigger.l.map(f, f))", "more than one nested loop"),
        ("s.matches(trigger.p)", "a regular expression that isn't a short literal"),
        ("s.matches('(?i)a')", "a regular expression with (?) groups or unsupported escapes"),
        ("s.matches('\\\\pL')", "a regular expression with (?) groups or unsupported escapes"),
        ("s.matches('[\\\\p{L}]{4}')", "a regular expression with (?) groups or unsupported escapes"),
        ("s.matches('\\\\x41')", "a regular expression with (?) groups or unsupported escapes"),
        ("timestamp(trigger.t).getHours('Europe/Paris')", "a named time zone (only UTC and fixed offsets run inline)"),
        ("timestamp(trigger.t).getHours(trigger.zone)", "a named time zone (only UTC and fixed offsets run inline)"),
    ],
)
def test_outside_the_allow_list(expr: str, reason: str) -> None:
    with pytest.raises(estimate.NotLocal) as e:
        bounds(expr)
    assert e.value.reason == reason


def test_plain_regular_expressions_are_allowed() -> None:
    assert bounds("s.matches('^ap\\\\d+\\\\.[a-z]*\\\\s?(x|y)$')").iterations == 0


def test_fixed_zones_are_allowed() -> None:
    assert bounds("timestamp(trigger.t).getHours('UTC') + timestamp(trigger.t).getHours('-05:30')").iterations == 0
