# SPDX-License-Identifier: Apache-2.0
"""Gate 1 (spec §5.9): semantics against the CEL language definition, pinned for cel-expr-python 0.1.3.

Ported from the spike's 77 cases (branch spike/cel-evaluation, semantics.py). Expected values follow the language
definition; the few places where the pinned runtime deviates are pinned as DEVIATION, so an upgrade that changes
them is noticed. `cidr_contains` became fn-1's `cidrContains`; the datetime input case became `timestamp(run.now)`,
since bindings are plain JSON."""

import math
from typing import Any

import pytest

from dewpoint.engine.cel import runtime
from dewpoint.engine.cel import types as T

ERR, PARSE = "ERR", "PARSE"
M = {"a": 1, "b": {"c": "x"}, "n": None}
TRIGGER = {
    "topic": "device-events",
    "site": {"id": "s1", "name": "Paris-Opera"},
    "events": [
        {"type": "AP_DISCONNECTED", "mac": "5c5b35000001", "model": "AP45"},
        {"type": "AP_CONNECTED", "mac": "5c5b35000002", "model": "AP47"},
        {"type": "AP_DISCONNECTED", "mac": "5c5b35000003", "model": "AP12"},
    ],
    "payload": {"region": None},
}
EV = {"trigger": TRIGGER}

CASES: list[tuple[str, dict[str, Any], Any]] = [
    ("1 + 2", {}, 3),
    ("9223372036854775807 + 1", {}, ERR),
    ("-9223372036854775808 - 1", {}, ERR),
    ("7 / 2", {}, 3),
    ("-7 / 2", {}, -3),
    ("-7 % 2", {}, -1),
    ("1 / 0", {}, ERR),
    ("1.0 / 0.0", {}, math.inf),
    ("1u + 2u", {}, 3),
    ("0u - 1u", {}, ERR),
    ("int(2.9)", {}, 2),
    ("int(1e19)", {}, ERR),
    ("x == 1", {"x": 1.0}, True),
    ("x < y", {"x": 1, "y": 1.5}, True),
    ("x == y", {"x": 1, "y": "a"}, False),
    ("e.rssi > -70", {"e": {"rssi": -65.0}}, True),
    ("null == null", {}, True),
    ("m.n == null", {"m": M}, True),
    ("[1, 2] == [1, 2]", {}, True),
    ("{'a': 1} == {'a': 1}", {}, True),
    ("'a' + 'b'", {}, "ab"),
    ("size('héllo')", {}, 5),
    ("'hello'.contains('ell') && 'hello'.startsWith('he') && 'hello'.endsWith('lo')", {}, True),
    ("'abc'.matches('^a.c$')", {}, True),
    ("'é' < 'f'", {}, False),
    ("'x'.size()", {}, 1),
    ("size(b'abc')", {}, 3),
    ("int('42')", {}, 42),
    ("int('4.2')", {}, ERR),
    ("double('1.5')", {}, 1.5),
    ("string(1.5)", {}, "1.5"),
    ("string(true)", {}, "true"),
    ("type(1) == int", {}, True),
    ("string(42)", {}, "42"),
    ("bool('true')", {}, True),
    ("uint(3)", {}, 3),
    ("has(m.a)", {"m": M}, True),
    ("has(m.z)", {"m": M}, False),
    ("m.z", {"m": M}, ERR),
    ("m['a']", {"m": M}, 1),
    ("m.b.c", {"m": M}, "x"),
    ("m.a.c", {"m": M}, ERR),
    ("'a' in m && 2 in [1, 2]", {"m": M}, True),
    ("[1, 2, 3][5]", {}, ERR),
    ("[1] + [2]", {}, [1, 2]),
    ("size({'a': 1})", {}, 1),
    ("[1, 2, 3].all(x, x > 0)", {}, True),
    ("[1, 2, 3].exists(x, x > 2)", {}, True),
    ("[1, 2, 3].exists_one(x, x > 1)", {}, False),
    ("[1, 2, 3].filter(x, x % 2 == 1)", {}, [1, 3]),
    ("[1, 2, 3].map(x, x * x)", {}, [1, 4, 9]),
    ("{'a': 1, 'b': 2}.all(k, k in ['a', 'b'])", {}, True),
    ("false && (1 / 0 > 0)", {}, False),
    ("true || (1 / 0 > 0)", {}, True),
    ("(1 / 0 > 0) || true", {}, True),
    ("(1 / 0 > 0) && false", {}, False),
    ("true ? 1 : 1 / 0", {}, 1),
    ("{'a': 0, 'b': 5}.all(k, 10 / {'a': 0, 'b': 5}[k] > 3)", {}, False),
    ("timestamp('2024-01-01T00:00:00Z') + duration('1h') == timestamp('2024-01-01T01:00:00Z')", {}, True),
    ("timestamp('2024-01-01T00:00:00Z').getHours('Europe/Paris')", {}, 1),
    ("duration('90m').getMinutes()", {}, 90),
    ("timestamp('2024-03-10T12:00:00Z') - timestamp('2024-03-10T10:00:00Z') == duration('2h')", {}, True),
    ("timestamp('bad')", {}, ERR),
    ("timestamp('2024-01-01T10:30:00Z').getHours()", {}, 10),
    ("timestamp('2024-01-01T10:30:00Z').getDayOfWeek()", {}, 1),
    ("timestamp('2024-01-01T10:30:00Z').getFullYear()", {}, 2024),
    ("timestamp(run.now) > timestamp('2020-01-01T00:00:00Z')", {"run": {"now": "2024-01-01T00:00:00Z"}}, True),
    ("1 +", {}, PARSE),
    ("a..b", {}, PARSE),
    ("trigger.events.filter(e, e.type == 'AP_DISCONNECTED').size()", EV, 2),
    ("trigger.events.exists(e, e.model in ['AP45', 'AP47'] && e.mac.startsWith('5c5b35'))", EV, True),
    ("has(trigger.site) ? trigger.site.name : 'unknown'", EV, "Paris-Opera"),
    ("trigger.events.map(e, e.mac)[0]", EV, "5c5b35000001"),
    ("cidrContains('10.0.0.0/8', '10.1.2.3')", {}, True),
    # Deviations of the pinned runtime from the language definition: literal-typed heterogeneous comparisons are
    # rejected by the type checker (dyn values compare per spec at runtime, see the `x == 1` cases above).
    ("1 == 1.0", {}, PARSE),
    ("1 < 1.5", {}, PARSE),
    ("1 == 'a'", {}, PARSE),
    # Former probes, now pinned: no optional syntax, linear-time regex, heterogeneous list literals.
    ("trigger.payload.?region.orValue('global')", EV, PARSE),
    ("'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!'.matches('(a+)+$')", {}, False),
    ("[1, 'a']", {}, [1, "a"]),
    # Map operations that don't expose iteration order stay allowed (spec §5.5).
    ("{'b': 1, 'a': 2} == {'a': 2, 'b': 1}", {}, True),
    ("size({'b': 1, 'a': 2}) == 2 && 'a' in {'b': 1, 'a': 2}", {}, True),
]


@pytest.mark.parametrize(("expr", "variables", "expected"), CASES, ids=[c[0][:60] for c in CASES])
def test_semantics(expr: str, variables: dict[str, Any], expected: Any) -> None:
    decls = {name: T.DYN for name in variables}
    try:
        compiled = runtime.compile_checked(expr, decls)
    except runtime.CompileError:
        assert expected == PARSE
        return
    assert expected != PARSE, "compiled but the case expects a compile error"
    got = runtime.evaluate(compiled, variables)
    if expected == ERR:
        assert got.kind in ("error", "aborted"), got
    else:
        assert got.kind == "value" and got.value == expected and type(got.value) is type(expected), got


def test_the_corpus_keeps_every_ported_case() -> None:
    # The spike's 77 cases and 3 of its 4 probes (the uint-overflow probe is refused at binding now, see
    # test_bind.py), plus 2 map cases.
    assert len(CASES) == 82
