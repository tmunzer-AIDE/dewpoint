# SPDX-License-Identifier: Apache-2.0
"""A simulated step's data origin (the simulation design §7.4), sent by the server: from what its instances' final
attempts did and the step's type, or, with none, from where the run is (D-a5)."""

import pytest

from dewpoint.apps.step_summary import origin

ECHO, IF, DELAY, WAIT = "testkit.echo@1", "flow.if@1", "flow.delay@1", "flow.wait_until@1"


@pytest.mark.parametrize(
    ("type_ref", "statuses", "ended", "error_code", "expected"),
    [
        (ECHO, {"succeeded": 1}, True, None, "fixture_not_sent"),  # a plugin's fixture answered: nothing was sent
        (ECHO, {"failed": 2, "skipped": 9}, True, None, "fixture_not_sent"),
        (ECHO, {"running": 1}, False, None, "fixture_not_sent"),
        (IF, {"succeeded": 3}, True, None, "evaluated"),
        (IF, {"failed": 1}, True, None, "evaluated"),
        (DELAY, {"succeeded": 1}, True, None, "evaluated_not_waited"),  # §4.2: timers aren't waited
        (WAIT, {"succeeded": 1}, True, None, "evaluated_not_waited"),
        (ECHO, {"cancelled": 1, "skipped": 2}, True, None, "cancelled"),  # began, and was stopped
        (ECHO, {"not_started": 1, "skipped": 2}, True, None, "not_started"),
        (ECHO, {"skipped": 3}, True, None, "skipped"),
        (ECHO, {}, False, None, "not_reached_yet"),  # only while the run hasn't ended
        (ECHO, {}, True, None, "didnt_run"),
        (ECHO, {}, True, "cancelled", "didnt_run"),  # a cancel ends inside the workflow: B4b recorded what it stopped
        (ECHO, {}, True, "internal_error", "not_recorded"),  # D-a5: it ended outside the workflow
        (ECHO, {}, True, "terminated", "not_recorded"),
        (ECHO, {}, True, "history_lost", "not_recorded"),
    ],
)
def test_a_steps_origin_comes_from_its_instances_or_from_where_the_run_is(
    type_ref: str, statuses: dict[str, int], ended: bool, error_code: str | None, expected: str
) -> None:
    assert origin(type_ref, statuses, ended=ended, error_code=error_code) == expected
