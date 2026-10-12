# SPDX-License-Identifier: Apache-2.0
"""The most Temporal calls one item of each pass makes, from its code's longest path, derived from the passes' own
numbers (`evidence.PAGES`, `schedule_sync.EARLIER`), never written beside them (the owner's review of the 2b-4b M1
checkpoint 4, R6). Each pass's test pins its longest path to it. A pass's worst is its soft budget (`budget.PASS_S`)
and one item's calls, each at its own worst; no number here is approved as a cycle's bound."""

from dewpoint.apps.dispatcher import evidence, schedule_sync

VERIFY = 2  # `dispatch.verify`'s longest path: two describes (`started_by`); a request without an id, one history page
# dispatch and reconcile, 1 + VERIFY = 3: accepted provisionally by the owner (2026-10-10) rather than weaken the
# request-id identity to save a call; D16's production budget still needs measuring on the M4 server.


def calls() -> dict[str, int]:
    """The table, from the passes' numbers as they are now."""
    earlier = schedule_sync.EARLIER
    # live: the current one described, described again under its lock, created, described, updated, read back, its
    # creation wait counted (matching times); up to EARLIER earlier ones described, the one found paused
    live = 7 + earlier + 1
    # a tombstone: the current one described, its landing counted (matching times); then up to 1 + EARLIER described,
    # each paused or deleted
    tombstone = 2 + 2 * (1 + earlier)
    return {
        # its start; already started, `verify`: its chain's latest run described, its first one when that differs (the
        # start request id's identity, the start-check slice); a request with no id (from before 0052), its history's
        # first page instead
        "dispatch": 1 + VERIFY,
        # a describe; then a closed run's result, the namespace, or an uncertain start's `verify`
        "reconcile": 1 + VERIFY,
        "subruns": 2,  # a describe; then a closed run's result, or, NOT_FOUND, the namespace
        "cancels": 2,  # the cancel; NOT_FOUND, the namespace
        "sync": max(live, tombstone),
        "misses": 1,  # a describe
        "strays": 2,  # a describe; then a pause or a delete
        "evidence": 1 + evidence.PAGES,  # a describe (on a first visit), then up to PAGES history pages
        "matching": 0,  # the database only
        "recount": 0,  # the database only
    }


CALLS = calls()
