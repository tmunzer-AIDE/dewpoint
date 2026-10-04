# SPDX-License-Identifier: Apache-2.0
"""A schedule's timing (engine 2b spec §8.2; the owner's ruling 9): five-field cron in exactly the forms whose meaning
`test_temporal_contract.py` pins as Temporal's own, an interval of at least 60 s, an IANA time zone and a catch-up
window of 1 minute to 24 hours. A form Temporal reads otherwise than cron usually does, a day of the month and a day of
the week restricted together, is refused rather than accepted under a meaning of Dewpoint's."""

import pytest

from dewpoint.apps.schedules import TIMING_CODES, cron_problems, timing_problems
from tests.apps.worker.test_temporal_contract import CRON


@pytest.mark.parametrize("cron", sorted({c for c, *_ in CRON} - {"0 9 13 * 5"}))
def test_every_pinned_form_but_both_day_fields_is_accepted(cron: str) -> None:
    assert cron_problems(cron) == []


@pytest.mark.parametrize(
    ("cron", "code"),
    [
        ("0 9 13 * 5", "cron_day_fields"),  # Temporal: both must match; cron: either
        ("0 9 */2 * MON", "cron_day_fields"),
        ("0 9 * *", "cron_fields"), ("0 0 9 * * *", "cron_fields"), ("@daily", "cron_fields"), ("", "cron_fields"),
        ("0 9 L * *", "cron_syntax"), ("0 9 ? * *", "cron_syntax"), ("0 9 * * 5#2", "cron_syntax"),
        ("0 9 15W * *", "cron_syntax"), ("H 9 * * *", "cron_syntax"), ("0 9 * JAN-MON *", "cron_syntax"),
        ("0 0 JAN * *", "cron_syntax"), ("5/15 * * * *", "cron_syntax"), ("0,,5 * * * *", "cron_syntax"),
        ("60 * * * *", "cron_range"), ("0 24 * * *", "cron_range"), ("0 0 0 * *", "cron_range"),
        ("0 0 * 13 *", "cron_range"), ("0 0 * * 8", "cron_range"), ("*/0 * * * *", "cron_range"),
        ("5-1 * * * *", "cron_range"), ("0 9-17/0 * * *", "cron_range"),
    ],
)  # fmt: skip
def test_any_other_form_is_refused_with_its_code(cron: str, code: str) -> None:
    assert cron_problems(cron) == [code]
    assert code in TIMING_CODES


def test_a_timing_is_a_cron_or_an_interval_in_a_known_zone_with_a_bounded_catch_up() -> None:
    assert timing_problems(cron="0 9 * * 1-5", every_s=None, offset_s=0, time_zone="Europe/Paris", catchup_s=600) == []
    assert timing_problems(cron=None, every_s=60, offset_s=59, time_zone="UTC", catchup_s=60) == []
    assert timing_problems(cron=None, every_s=None, offset_s=0, time_zone="UTC", catchup_s=600) == [
        {"field": "cron", "code": "timing_missing"}
    ]
    assert timing_problems(cron="* * * * *", every_s=60, offset_s=0, time_zone="UTC", catchup_s=600) == [
        {"field": "every_s", "code": "timing_both"}
    ]
    assert timing_problems(cron=None, every_s=59, offset_s=0, time_zone="UTC", catchup_s=600) == [
        {"field": "every_s", "code": "interval_too_short"}
    ]
    assert timing_problems(cron=None, every_s=60, offset_s=60, time_zone="UTC", catchup_s=600) == [
        {"field": "offset_s", "code": "interval_offset"}
    ]
    for zone in ("Mars/Olympus", "../etc/passwd", "europe/paris", ""):
        assert timing_problems(cron="0 9 * * *", every_s=None, offset_s=0, time_zone=zone, catchup_s=600) == [
            {"field": "time_zone", "code": "time_zone_unknown"}
        ]
    for catchup in (59, 86_401):
        assert timing_problems(cron="0 9 * * *", every_s=None, offset_s=0, time_zone="UTC", catchup_s=catchup) == [
            {"field": "catchup_window_s", "code": "catchup_window"}
        ]
    assert timing_problems(cron="0 9 13 * 5", every_s=None, offset_s=0, time_zone="UTC", catchup_s=600) == [
        {"field": "cron", "code": "cron_day_fields"}
    ]
