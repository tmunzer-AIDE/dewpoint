# SPDX-License-Identifier: Apache-2.0
"""Compose's anchor job (`dewpoint audit anchor --every`): a run, then a wait, until a stop is requested; the run in
hand ends and no other begins; a run that fails ends the job, never retried, so a job that stopped anchoring can't
look alive (Compose's `restart: "no"`)."""

import asyncio

import pytest
from structlog.testing import capture_logs

from dewpoint.apps import audit_anchor, stopping


async def test_it_runs_then_waits_until_a_stop_ends_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def anchor() -> int:
        calls.append("anchor")
        return 1

    async def pause(requested: asyncio.Event, seconds: float) -> None:
        calls.append(f"wait {seconds:g}")
        if calls.count("anchor") == 2:
            requested.set()  # Compose's stop, during the second wait

    monkeypatch.setattr(stopping, "pause", pause)
    with capture_logs() as logged:
        await audit_anchor.run(anchor, every=900, stop_requested=asyncio.Event(),
                               anchored=lambda n: calls.append(f"anchored {n}"))  # fmt: skip
    assert calls == ["anchor", "anchored 1", "wait 900", "anchor", "anchored 1", "wait 900"]
    assert [entry["event"] for entry in logged] == ["audit_anchor_stopped"]


async def test_a_stop_during_a_run_lets_it_end_and_begins_no_other() -> None:
    """The real wait, an hour long, ends at once: the test is bounded, never timed."""
    requested = asyncio.Event()
    calls: list[str] = []

    async def anchor() -> int:
        calls.append("anchor")
        requested.set()  # SIGTERM while the run writes its anchors
        await asyncio.sleep(0)
        calls.append("anchor ended")
        return 2

    await asyncio.wait_for(audit_anchor.run(anchor, every=3600, stop_requested=requested,
                                            anchored=lambda n: calls.append(f"anchored {n}")), 10)  # fmt: skip
    assert calls == ["anchor", "anchor ended", "anchored 2"]


async def test_a_failed_run_ends_the_job_with_its_exception() -> None:
    calls: list[str] = []

    async def anchor() -> int:
        calls.append("anchor")
        raise ConnectionError("the database went away")

    with capture_logs() as logged, pytest.raises(ConnectionError):
        await audit_anchor.run(anchor, every=900, stop_requested=asyncio.Event(), anchored=lambda n: None)
    assert calls == ["anchor"]  # no retry
    assert [entry["event"] for entry in logged] == []  # no stop line: it didn't stop, it failed
