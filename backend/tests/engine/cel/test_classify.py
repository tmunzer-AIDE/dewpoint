# SPDX-License-Identifier: Apache-2.0
import pytest

from dewpoint.engine.cel import caps, classify, estimate, runtime
from dewpoint.engine.cel import types as T

DECLS = {"trigger": T.MAP, "steps": T.MAP, "s": T.STRING, "trigger.events": T.LIST_OF_MAPS, "m": T.MAP}


def _classify(expr: str) -> classify.Classification:
    return classify.classify(expr, runtime.compile_checked(expr, DECLS).checked)


def _problems(expr: str) -> list[str]:
    return [p.code for p in classify.order_problems(runtime.compile_checked(expr, DECLS).checked)]


@pytest.mark.parametrize(
    ("expr", "codes"),
    [
        ("m.map(k, k)", ["cel.map_iteration"]),
        ("m.all(k, k != '')", ["cel.map_iteration"]),  # boolean macros too (spec §5.5)
        ("trigger.items.map(i, i)", ["cel.unproven_list"]),
        ("trigger.events.map(e, e.tags.exists(t, t == 'x'))", ["cel.unproven_list"]),  # at any depth
        ("sortedKeys(m).map(k, m[k])", []),
        ("asList(trigger.items).map(i, i)", []),
        ("'a' in m && size(m) > 0 && m == {'a': 1}", []),  # order-free map operations stay allowed
    ],
)
def test_order_problems(expr: str, codes: list[str]) -> None:
    assert _problems(expr) == codes


@pytest.mark.parametrize(
    "expr",
    [
        "trigger.x == 1 && s.startsWith('a')",
        "trigger.events.filter(e, e.type == 'AP_DISCONNECTED').size()",
        "trigger.events.map(e, e.mac)",
        "sortedKeys(m).map(k, k)",
        "timestamp(trigger.at).getHours('+02:00') > 3",
        "s.matches('^ap[0-9]+$')",
        "ipInCidr(trigger.ip, '10.0.0.0/8') || macOui(trigger.mac) == '5c5b35'",
    ],
)
def test_local_subset(expr: str) -> None:
    got = _classify(expr)
    assert got.mode == "local" and got.iterations is not None and got.bytes is not None, got


@pytest.mark.parametrize(
    ("expr", "reason"),
    [
        ("trigger.events.map(e, trigger.events.map(f, f))", "more than one nested loop"),
        ("s.matches(trigger.pattern)", "a regular expression that isn't a short literal"),
        ("timestamp(trigger.at).getHours('Europe/Paris')", "a named time zone (only UTC and fixed offsets run inline)"),
        ("trigger.events.map(e, s + s + s)", "may need more than 4 MiB of memory"),
        (
            "trigger.events.map(e, e.mac).filter(m, m != '').map(m, m + 'a').filter(m, m != 'b')",
            "may need more than 4 MiB of memory",  # four accumulators kept at once
        ),
        ("'x' + '" + "a" * 4100 + "'", "longer than 4,096 characters"),
        (
            " && ".join(["trigger.events.all(e, e.mac != 'x')"] * 50),  # 50 x 200 = 10,000: the runtime stops there
            "may iterate 10,000 times or more with large inputs",
        ),
        (
            "trigger.events.exists(e, " + " || ".join([f"s.matches('z{i}')" for i in range(50)]) + ")",  # scans
            "does too much work per item to run inline",
        ),
    ],
)
def test_activity_reasons(expr: str, reason: str) -> None:
    got = _classify(expr)
    assert (got.mode, got.reason) == ("activity", reason)


def test_bounds_are_affine_in_the_element() -> None:
    """`map(e, e.mac)` stays near the list's own size instead of 1,000 x the largest input."""
    got = _classify("trigger.events.map(e, e.mac)")
    assert got.iterations == caps.LIST_LENGTH
    retained = caps.ACCUMULATOR_SLOT * caps.LIST_LENGTH * (caps.LIST_LENGTH + 1) // 2
    assert got.bytes is not None and got.bytes <= 2 * caps.INPUT_MODEL_BYTES + retained


def test_a_three_step_chain_at_the_caps_stays_local() -> None:
    got = _classify("trigger.events.map(e, e.mac).filter(m, m != '').map(m, m + 'a')")
    assert got.mode == "local", got


def test_every_fn1_overload_has_a_size_rule() -> None:
    from dewpoint.engine.cel import functions

    assert functions.OVERLOAD_IDS <= estimate.LOCAL_OVERLOADS
