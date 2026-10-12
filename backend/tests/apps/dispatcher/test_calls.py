# SPDX-License-Identifier: Apache-2.0
"""The most Temporal calls one item of each pass makes (`calls.CALLS`), derived from the passes' own numbers, never
written beside them (the owner's review of the 2b-4b M1 checkpoint 4, R6): a change to `evidence.PAGES` or
`schedule_sync.EARLIER` changes the table, and each pass's test pins its items to it."""

from dewpoint.apps.dispatcher import calls, evidence, schedule_sync


def test_the_table_follows_the_passes_own_numbers(monkeypatch) -> None:
    assert calls.CALLS["evidence"] == 1 + evidence.PAGES
    live, tombstone = 7 + schedule_sync.EARLIER + 1, 2 + 2 * (1 + schedule_sync.EARLIER)
    assert calls.CALLS["sync"] == max(live, tombstone)
    monkeypatch.setattr(evidence, "PAGES", 3)
    monkeypatch.setattr(schedule_sync, "EARLIER", 6)
    derived = calls.calls()
    assert derived["evidence"] == 4 and derived["sync"] == max(7 + 6 + 1, 2 + 2 * 7)
