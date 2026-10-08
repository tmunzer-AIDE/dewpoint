# SPDX-License-Identifier: Apache-2.0
"""B3's pure parts: attention comes from live runs only, and a draft is hashed once per revision."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from dewpoint.apps import workflow_summary as summary
from dewpoint.engine.graph.model import graph_hash, parse_graph
from tests.support.graphs import G

GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data()
AT = datetime(2026, 10, 6, tzinfo=UTC)


def stats(live: str | None, simulated: str | None) -> summary.RunStats:
    return summary.RunStats(
        last_live=summary.LastRun(live, AT) if live else None,
        last_simulated=summary.LastRun(simulated, AT) if simulated else None,
        live_24h=0,
        simulated_24h=0,
    )


@pytest.mark.parametrize(
    ("live", "simulated", "expected"),
    [
        ("failed", "succeeded", ["last_run_failed"]),  # a later good simulation never clears a live failure
        ("deadline_exceeded", None, ["last_run_failed"]),
        ("succeeded", "failed", []),  # a failed simulation never needs attention
        (None, "deadline_exceeded", []),
        ("cancelled", None, []),
        ("running", None, []),
    ],
)
def test_only_a_live_run_needs_attention(live: str | None, simulated: str | None, expected: list[str]) -> None:
    assert summary.attention(stats(live, simulated), published=True, blocked=[]) == expected


def test_a_version_that_cant_run_needs_attention() -> None:
    assert summary.attention(stats(None, None), published=True, blocked=["testkit.echo@1"]) == ["not_executable"]
    assert summary.attention(stats(None, None), published=False, blocked=[]) == []


async def test_a_draft_is_hashed_once_per_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed: list[int] = []
    real = summary.parse_graph
    monkeypatch.setattr(summary, "parse_graph", lambda d: parsed.append(1) or real(d))
    hashes, wid = summary.DraftHashes(kept=8), uuid.uuid4()
    first = await hashes.of([(wid, 1, GRAPH)])
    again = await hashes.of([(wid, 1, GRAPH)])
    assert first == again == {wid: graph_hash(parse_graph(GRAPH))} and len(parsed) == 1
    await hashes.of([(wid, 2, GRAPH)])
    assert len(parsed) == 2


async def test_a_draft_that_doesnt_parse_has_no_hash() -> None:
    wid = uuid.uuid4()
    assert await summary.DraftHashes(kept=8).of([(wid, 1, {"graph_format": 9})]) == {wid: None}


async def test_the_kept_hashes_are_bounded() -> None:
    hashes = summary.DraftHashes(kept=2)
    drafts = [(uuid.uuid4(), 1, GRAPH) for _ in range(3)]
    assert len(await hashes.of(drafts)) == 3  # every draft asked for is answered
    assert len(hashes) == 2  # the oldest is forgotten


async def test_a_read_answers_what_it_found_kept_even_when_another_evicts_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two lists at once, the bound passed between them: each answers every draft it asked for (never a KeyError)."""
    gates: list[asyncio.Event] = []
    both_waiting = asyncio.Event()

    async def held(fn: Any) -> Any:  # the thread's work, released when the test says
        gate = asyncio.Event()
        gates.append(gate)
        if len(gates) == 2:
            both_waiting.set()
        await gate.wait()
        return fn()

    hashes = summary.DraftHashes(kept=2)
    kept = (uuid.uuid4(), 1, GRAPH)
    await hashes.of([kept])  # kept, with the real thread
    monkeypatch.setattr(summary.asyncio, "to_thread", held)
    first = asyncio.create_task(hashes.of([kept, (uuid.uuid4(), 1, GRAPH)]))  # finds `kept`, computes the other
    second = asyncio.create_task(hashes.of([(uuid.uuid4(), 1, GRAPH), (uuid.uuid4(), 1, GRAPH)]))
    await both_waiting.wait()
    gates[1].set()  # the second ends first: its two new hashes evict `kept`
    await second
    gates[0].set()
    assert len(await first) == 2


async def test_a_draft_being_saved_is_hashed_but_never_kept() -> None:
    before = len(summary.HASHES)
    assert await summary.hash_now(GRAPH) == graph_hash(parse_graph(GRAPH))
    assert len(summary.HASHES) == before
