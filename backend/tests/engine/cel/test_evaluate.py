# SPDX-License-Identifier: Apache-2.0
import datetime

import pytest

from dewpoint.engine.cel import canonical
from dewpoint.engine.cel import evaluate as E
from tests.engine.cel.support import make_record
from tests.engine.cel.test_bind import view


def outcome(expr: str, **overrides: object) -> E.Outcome:
    return E.evaluate_local(make_record(expr, item="index" in overrides), view(**overrides))  # type: ignore[arg-type]


def test_values_come_back_canonical() -> None:
    assert outcome("{'b': 1, 'a': {'d': 2, 'c': 3}}").value == {"a": {"c": 3, "d": 2}, "b": 1}
    assert outcome("timestamp(run.now) + duration('90m')").value == "2026-09-26T01:30:01Z"
    assert outcome("duration('1.5s')").value == "1.5s"
    assert outcome("1u + 2u").value == 3


@pytest.mark.parametrize(
    ("expr", "code"),
    [
        ("trigger.nope", E.EVALUATION_ERROR),
        ("1 / 0", E.EVALUATION_ERROR),
        ("asList(trigger.site)", E.TYPE_MISMATCH),
        ("macNormalize('nope')", E.EVALUATION_ERROR),
        ("b'x'", E.NON_JSON),
        ("{1: 'a'}", E.NON_JSON),
        ("1.0 / 0.0", E.NON_JSON),
    ],
)
def test_error_outcomes(expr: str, code: str) -> None:
    got = outcome(expr)
    assert not got.ok and got.error == code, got


def test_the_iteration_budget_is_its_own_outcome() -> None:
    got = outcome("trigger.l.all(a, trigger.l.all(b, true))", trigger={"l": list(range(200))})
    assert got.error == E.ITERATION_BUDGET


def test_output_over_256_kib_is_refused() -> None:
    got = outcome("trigger.s + trigger.s + trigger.s + trigger.s + trigger.s", trigger={"s": "x" * 60_000})
    assert got.error == E.OUTPUT_TOO_LARGE


def test_binding_failures_are_type_mismatches() -> None:
    assert outcome("vars.x == 1", vars={"x": 2**64}).error == E.TYPE_MISMATCH


def test_outcomes_round_trip() -> None:
    for o in (E.Outcome(value={"a": [1]}), E.Outcome(error=E.TIMEOUT, message="m")):
        assert E.Outcome.from_json(o.to_json()) == o


def test_canonical_time_formats() -> None:
    t = datetime.datetime(2024, 1, 1, 0, 0, 0, 500_000, tzinfo=datetime.UTC)
    assert canonical.rfc3339(t) == "2024-01-01T00:00:00.5Z"
    assert canonical.seconds(datetime.timedelta(seconds=-0.5)) == "-0.5s"
    assert canonical.seconds(datetime.timedelta(0)) == "0s"
    assert canonical.seconds(datetime.timedelta(days=1)) == "86400s"
