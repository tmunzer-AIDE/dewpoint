# SPDX-License-Identifier: Apache-2.0
"""Collections compact (engine 2b spec §5.3): a loop's collected values and its failures are immutable segment claims
plus a short inline tail. The tail is claimed as one segment past SEGMENT_BYTES, or earlier when the budget needs
it; the segment list is a container too, claimed as index segments. A loop whose collection spilled ends with one
claim of the whole list, assembled from its segments, so its handle addresses each item by position. A batch child
writes its segments where its parent's loop names them, and returns its collection for the parent to merge."""

import asyncio
import json
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dewpoint.engine.handles import ClaimRef, StoredClaim, resolve_value
from dewpoint.engine.runtime import scheduler as S
from dewpoint.engine.runtime.budget import Budget
from dewpoint.engine.runtime.scheduler import Failure, Instance, Scheduler, Spill, assembled
from tests.engine.runtime.support import program
from tests.support.graphs import G

ECHO, LOOP = "testkit.echo@1", "flow.loop@1"
PREFIX = "t:1:run:2"


class Claims:
    """What `claims.spill` writes: plain values, forwarding claims, joined lists, and assembled collections."""

    def __init__(self) -> None:
        self.held: dict[str, Any] = {}

    async def stored(self, claim_id: str) -> Any:
        return self.held[claim_id]

    async def write(self, entry: dict[str, Any]) -> None:
        if "assemble" in entry:
            value = await assembled(entry["assemble"], self.stored)
        else:
            value = entry["value"]
            if entry.get("prev"):
                before = self.held[entry["prev"]]
                forward = {
                    k: v if ClaimRef.of(v) else ClaimRef(entry["prev"], "/" + k).to_json() for k, v in before.items()
                }
                value = {**forward, **value}
        assert self.held.setdefault(entry["id"], value) == value
        self.held[entry["id"]] = value

    async def read(self, value: Any) -> Any:
        async def fetch(claim_id: str) -> StoredClaim:
            return StoredClaim(self.held[claim_id], ())

        return (await resolve_value(value, fetch)).value


def loop_graph() -> G:
    return G().node("l", LOOP, {"items": [1]}, on_error="continue").node("x", ECHO).edge("l", "x", "body")


def drive(s: Scheduler, claims: Claims, values: dict[int, Any], failing: set[int] = frozenset()) -> list[Spill]:
    """Run the loop to its end: each iteration succeeds and collects `values[index]`, or fails when its index is in
    `failing`; every claim lands at once. Returns the claims made."""
    made: list[Spill] = []
    while s.ended is None:
        spills = s.take_spills()
        for sp in spills:
            asyncio.run(claims.write(sp.entry))
            s.spilled(sp.owner, sp.which, sp.first)
        made += spills
        ready, collects = s.take_ready(), s.take_collects()
        for inst in ready:
            if s.step(inst).ref == LOOP:
                continue
            index = inst.scope[-1][1]
            if index in failing:
                s.fail(inst, Failure("testkit.boom", f"item {index} broke"))
            else:
                s.succeed(inst, {})
        for c in collects:
            s.collected(c.loop, c.index, values[c.index])
        if not spills and not ready and not collects and not s.take_spills():
            break
    return made


def started_loop(n: int, **kwargs: Any) -> tuple[Scheduler, Instance]:
    s = Scheduler(program(loop_graph()), prefix=PREFIX, **kwargs)
    s.start()
    [loop] = s.take_ready()
    s.open_loop(loop, list(range(n)), concurrency=3, stop_on_error=False)
    return s, loop


def output(s: Scheduler, claims: Claims) -> Any:
    return asyncio.run(claims.read(s.scopes[()].results["l"]["output"]))


def test_a_loop_that_collects_within_the_budget_ends_with_a_plain_list() -> None:
    s, _ = started_loop(5)
    claims = Claims()
    assert drive(s, claims, {i: i * 10 for i in range(5)}) == []
    assert s.scopes[()].results["l"]["output"] == {"items": [0, 10, 20, 30, 40], "failures": [], "count": 5}


def test_past_the_budget_the_tail_becomes_a_segment_and_the_output_is_assembled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(S, "LIVE_BUDGET", 2_000)
    s, _ = started_loop(12)
    claims = Claims()
    values = {i: f"{i:02d}" + "v" * 250 for i in range(12)}
    made = drive(s, claims, values)
    assert "c" in {sp.which for sp in made} and "ac" in {sp.which for sp in made}
    handle = ClaimRef.of(s.scopes[()].results["l"]["output"]["items"])
    assert handle is not None and handle.pointer == ""  # one claim: its handle addresses each item by position
    assert output(s, claims)["items"] == [values[i] for i in range(12)]


def test_a_tail_past_segment_bytes_is_claimed_whatever_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S, "SEGMENT_BYTES", 600)
    s, _ = started_loop(10)
    claims = Claims()
    values = {i: "w" * 200 for i in range(10)}
    made = drive(s, claims, values)
    assert [sp.which for sp in made].count("c") >= 3
    assert output(s, claims)["items"] == ["w" * 200] * 10


def test_a_growing_segment_list_is_claimed_as_index_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S, "SEGMENT_BYTES", 150)
    monkeypatch.setattr(S, "LIVE_BUDGET", 1_200)
    s, _ = started_loop(120)
    claims = Claims()
    values = {i: f"{i:03d}" + "s" * 160 for i in range(120)}
    made = drive(s, claims, values)
    assert "xc" in {sp.which for sp in made}
    assert output(s, claims)["items"] == [values[i] for i in range(120)]


def test_failures_are_entries_in_index_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S, "LIVE_BUDGET", 1_500)
    s, _ = started_loop(30)
    claims = Claims()
    failing = {3, 11, 17, 25}
    drive(s, claims, {i: "v" * 100 for i in range(30)}, failing)
    result = output(s, claims)
    assert result["failures"] == [
        {"index": i, "code": "testkit.boom", "message": f"item {i} broke"} for i in sorted(failing)
    ]
    assert result["items"] == [None if i in failing else "v" * 100 for i in range(30)]


def test_a_batch_child_writes_its_segments_for_its_parent_to_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    """The child's segments are named by the parent loop's base; it returns its collection, not its values."""
    monkeypatch.setattr(S, "LIVE_BUDGET", 2_000)
    parent = Scheduler(program(loop_graph()), prefix=PREFIX)
    parent.start()
    [loop] = parent.take_ready()
    parent.open_loop(loop, list(range(150)), concurrency=1, stop_on_error=False, batch=100)
    claims = Claims()
    values = {i: f"{i:03d}" + "b" * 100 for i in range(150)}
    while parent.ended is None:
        for b in parent.take_batches():
            child = Scheduler(program(loop_graph()), budget=Budget(100, root=False), prefix=f"{PREFIX}/b{b.start}")
            child.start_batch(loop.step, [S.OuterScope((), {})], b.items, offset=b.start, concurrency=5,
                              stop_on_error=False, base=parent.collect_base(loop))  # fmt: skip
            drive(child, claims, values)
            assert child.outcome is not None and child.outcome.collection is not None
            parent.batch_done(loop, b.start, child.outcome)
        for sp in parent.take_spills():
            asyncio.run(claims.write(sp.entry))
            parent.spilled(sp.owner, sp.which, sp.first)
    assert output(parent, claims)["items"] == [values[i] for i in range(150)]


@settings(
    max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture]
)
@given(data=st.data())
def test_random_collections_read_back_whole(data: st.DataObject, monkeypatch: pytest.MonkeyPatch) -> None:
    """Random budgets and segment sizes, iterations collecting and failing in random order, claims landing in random
    order around snapshots: the loop's output reads back as what was collected."""
    monkeypatch.setattr(S, "LIVE_BUDGET", data.draw(st.sampled_from([800, 2_000, 1_048_576]), label="budget"))
    monkeypatch.setattr(S, "SEGMENT_BYTES", data.draw(st.sampled_from([300, 1_000, 262_144]), label="segment"))
    n = data.draw(st.integers(1, 40), label="items")
    s, _ = started_loop(n)
    claims, out, running, collects = Claims(), [], [], []
    values = {i: "x" * data.draw(st.sampled_from([0, 40, 300]), label="value") for i in range(n)}
    failing = {i for i in range(n) if data.draw(st.integers(0, 6), label="fail") == 0}
    while s.ended is None:
        out += s.take_spills()
        running += [i for i in s.take_ready() if s.step(i).ref != LOOP]
        collects += s.take_collects()
        assert s.live == s.recount()
        if data.draw(st.integers(0, 6), label="snapshot") == 0 and s.live <= S.LIVE_BUDGET:
            s.take_settled()
            s = Scheduler.from_json(s.program, json.loads(json.dumps(s.to_json(check=True))), prefix=PREFIX)
        choices = len(out) + len(running) + len(collects)
        if not choices:
            break
        pick = data.draw(st.integers(0, choices - 1), label="pick")
        if pick < len(out):
            sp = out.pop(pick)
            asyncio.run(claims.write(sp.entry))
            s.spilled(sp.owner, sp.which, sp.first)
        elif pick < len(out) + len(running):
            inst = running.pop(pick - len(out))
            index = inst.scope[-1][1]
            if index in failing:
                s.fail(inst, Failure("testkit.boom", "broke"))
            else:
                s.succeed(inst, {})
        else:
            c = collects.pop(pick - len(out) - len(running))
            s.collected(c.loop, c.index, values[c.index])
    assert s.ended is not None and s.ended.status == "succeeded"
    result = output(s, claims)
    assert result["items"] == [None if i in failing else values[i] for i in range(n)]
    assert [f["index"] for f in result["failures"]] == sorted(failing)
