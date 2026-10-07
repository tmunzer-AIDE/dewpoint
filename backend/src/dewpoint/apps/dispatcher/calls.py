# SPDX-License-Identifier: Apache-2.0
"""The most Temporal calls one item of each pass makes, from its code's longest path, derived from the passes' own
numbers (`evidence.PAGES`, `schedule_sync.EARLIER`), never written beside them (the owner's review of the 2b-4b M1
checkpoint 4, R6). Each pass's test pins its longest path to it. A pass's worst is its soft budget (`budget.PASS_S`)
and one item's calls, each at its own worst; no number here is approved as a cycle's bound."""

from dewpoint.apps.dispatcher import evidence, schedule_sync


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
        "dispatch": 2,  # its start; already started, its history's first page (verified against it)
        "reconcile": 2,  # a describe; then a closed run's result, an uncertain start's history page, or the namespace
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
