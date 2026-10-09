# SPDX-License-Identifier: Apache-2.0
"""D6's independent monitor (#3; the owner's acceptance condition; 2b-4b M4): Object Lock protects an anchor once
written, not the writing of the next one, so a compromised database could drop a scope or withhold its anchors. Off
the database host, the monitor keeps the expected scopes and their cadence (its roster) and each scope's high-water
mark (its own state), and alerts on a scope gone from the database (D6.10), an anchor withheld past its cadence
(D6.10), and a high-water mark lost or rolled back (D6.11). Healthy, it says nothing. Its alert destination and host
are the owner's before readiness; locally, structured logs and a non-zero exit."""

from datetime import UTC, datetime, timedelta

from dewpoint.core.audit.monitor import Roster, Scope, watch

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
ROSTER = Roster(default=timedelta(minutes=30), scopes={"platform": timedelta(minutes=15)})


def test_a_healthy_deployment_raises_nothing_and_its_marks_move_up() -> None:
    database = {"platform": Scope(newest=12, oldest_unanchored=None), "t-1": Scope(newest=4, oldest_unanchored=None)}
    alerts, state = watch(ROSTER, {"platform": 10}, database, {"platform": 12, "t-1": 4}, NOW)
    assert alerts == [] and state == {"platform": 12, "t-1": 4}


def test_a_scope_gone_from_the_database_is_alerted_on() -> None:
    """One the roster names, never seen; and one the monitor saw before and the database no longer lists."""
    alerts, state = watch(ROSTER, {"t-1": 4}, {}, {"t-1": 4}, NOW)
    assert alerts == [("audit_scope_missing", "platform", "the roster's scope isn't in the database"),
                      ("audit_scope_missing", "t-1", "a scope seen before isn't in the database")]  # fmt: skip
    assert state == {"t-1": 4}


def test_an_anchor_withheld_past_its_cadence_is_alerted_on() -> None:
    late = Scope(newest=13, oldest_unanchored=NOW - timedelta(minutes=16))  # platform's cadence: 15 minutes
    on_time = Scope(newest=5, oldest_unanchored=NOW - timedelta(minutes=29))  # the default: 30
    alerts, _ = watch(ROSTER, {}, {"platform": late, "t-1": on_time}, {"platform": 12, "t-1": 4}, NOW)
    assert alerts == [("audit_anchor_overdue", "platform", "seq 13 unanchored for more than 15 minutes")]


def test_a_high_water_mark_rolled_back_is_alerted_on_and_kept() -> None:
    """The bucket's newest anchor for a scope below what the monitor saw: an anchor hidden or gone. The mark stays
    where it was, so the alert stays until it's explained."""
    database = {"platform": Scope(newest=12, oldest_unanchored=None)}
    alerts, state = watch(ROSTER, {"platform": 12}, database, {"platform": 9}, NOW)
    assert alerts == [("audit_high_water_rolled_back", "platform", "the bucket's newest anchor is seq 9, after 12")]
    assert state == {"platform": 12}


def test_a_lost_state_is_alerted_on_unless_it_is_being_set_up() -> None:
    database = {"platform": Scope(newest=12, oldest_unanchored=None)}
    alerts, state = watch(ROSTER, None, database, {"platform": 12}, NOW)
    assert alerts == [("audit_monitor_state_lost", "", "no high-water marks: lost, or never set up (--init)")]
    assert state == {"platform": 12}
    assert watch(ROSTER, None, database, {"platform": 12}, NOW, init=True) == ([], {"platform": 12})
