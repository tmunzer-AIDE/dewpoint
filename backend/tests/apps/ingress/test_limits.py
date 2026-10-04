# SPDX-License-Identifier: Apache-2.0
"""Ingress's limits before authentication (the owner's rulings 5 and 7): each address may fail 30 requests a minute in
a process, held in a bounded table in memory; and at most 32 requests are in flight in a process."""

from dewpoint.apps.ingress.limits import FailureLimiter, InFlight


def test_an_address_is_refused_once_it_has_failed_its_limit_until_its_minute_ends() -> None:
    limiter = FailureLimiter(failures=3, window_s=60)
    for t in (0.0, 1.0, 2.0):
        assert limiter.blocked("a", t) is None
        limiter.fail("a", t)
    assert limiter.blocked("a", 2.5) == 58  # whole seconds, rounded up, until the window that began at 0 ends
    assert limiter.blocked("b", 2.5) is None  # another address isn't affected
    assert limiter.blocked("a", 60.0) is None  # a new window


def test_failures_in_an_earlier_window_dont_count() -> None:
    limiter = FailureLimiter(failures=2, window_s=60)
    limiter.fail("a", 0.0)
    limiter.fail("a", 61.0)
    assert limiter.blocked("a", 61.5) is None


def test_the_table_is_bounded_dropping_the_address_that_failed_least_recently() -> None:
    limiter = FailureLimiter(failures=1, window_s=60, max_entries=2)
    limiter.fail("a", 0.0)
    limiter.fail("b", 30.0)
    limiter.fail("a", 31.0)  # a failed again: b is now the least recent
    limiter.fail("c", 70.0)  # b goes
    assert len(limiter) == 2
    assert limiter.blocked("b", 70.0) is None
    assert limiter.blocked("c", 70.0) is not None


def test_in_flight_admits_up_to_its_limit() -> None:
    gate = InFlight(2)
    assert gate.try_acquire() and gate.try_acquire()
    assert not gate.try_acquire()
    gate.release()
    assert gate.try_acquire()
