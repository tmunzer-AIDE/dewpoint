# SPDX-License-Identifier: Apache-2.0
"""Containers and their claims (engine 2b spec §5.3, component 5). After every change, while the live state passes
LIVE_BUDGET, the largest spillable container (past HANDLE_MAX) is claimed and replaced by its handle, ties broken by
scheduling order; what's on its way to a claim still counts until it's written, and the choice discounts it. Here: a
scope's result set and its item, the variables, and an undo record. A reference into a claimed container reads by
handle; the workflow never reads the claim. The budget is lowered so small values show it."""

import asyncio
import dataclasses
import json
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dewpoint.engine.handles import ClaimRef, StoredClaim, resolve_value
from dewpoint.engine.runtime import scheduler as S
from dewpoint.engine.runtime.budget import Budget
from dewpoint.engine.runtime.scheduler import Instance, Scheduler, Spill, size
from tests.engine.runtime.support import name, program
from tests.support.graphs import G

ECHO, LOOP, SET = "testkit.echo@1", "flow.loop@1", "flow.set_variables@1"
BUDGET = 2_000


@pytest.fixture(autouse=True)
def lowered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S, "LIVE_BUDGET", BUDGET)


def started(g: G, **kwargs: Any) -> Scheduler:
    s = Scheduler(program(g), prefix="t:1:run:2", **kwargs)
    s.start()
    return s


def land(s: Scheduler, spills: list[Spill]) -> None:
    """The spills' claims are written: each container's part is in its claim now."""
    for sp in spills:
        s.spilled(sp.owner, sp.which, sp.first)


def steps(*keys: str) -> G:
    """Root steps, and `z`, which keeps running so the run doesn't end."""
    g = G().node("z", ECHO)
    for k in keys:
        g.node(k, ECHO)
    return g


def test_past_the_budget_the_largest_container_is_claimed_and_still_counts_until_it_lands() -> None:
    s = started(steps("a", "b", "c"))
    a, b, c, _ = s.take_ready()
    s.succeed(a, {"v": "a" * 900})
    s.succeed(b, {"v": "b" * 900})
    assert s.take_spills() == []  # within the budget
    s.succeed(c, {"v": "c" * 400})
    [sp] = s.take_spills()
    assert (sp.which, sp.owner.scope, sorted(sp.entry["value"])) == ("r", (), ["a", "b", "c"])
    assert s.live > BUDGET and s.live == s.recount()  # on its way: still counted
    assert s.result_of(s.scopes[()], "a") == {"output": {"v": "a" * 900}}  # and still read inline
    land(s, [sp])
    head = ClaimRef(sp.entry["id"])
    assert s.live <= BUDGET and s.live == s.recount()
    assert s.result_of(s.scopes[()], "a") == head.extend("a").to_json()  # read by handle now


def test_a_second_claim_of_a_result_set_forwards_to_the_first() -> None:
    """Its claim names the previous one: the activity writes the new results with forwarding handles to the older
    ones, so one handle reaches every result claimed (§3.2: in two hops at most)."""
    s = started(steps("a", "b", "c", "d"))
    a, b, c, d, _ = s.take_ready()
    for inst in (a, b, c):
        s.succeed(inst, {"v": "x" * 800})
    [first] = s.take_spills()
    land(s, [first])
    s.succeed(d, {"v": "y" * 2_000})
    [second] = s.take_spills()
    assert (second.which, second.entry["prev"], sorted(second.entry["value"])) == ("r", first.entry["id"], ["d"])
    land(s, [second])
    assert s.result_of(s.scopes[()], "a") == ClaimRef(second.entry["id"]).extend("a").to_json()


def test_the_largest_container_goes_first_ties_by_scheduling_order() -> None:
    """Two iteration scopes with the same results: the earlier one's goes first, and that's enough."""
    g = G().node("l", LOOP, {"items": [1]}).node("x", ECHO).edge("l", "x", "body")
    s = started(g)
    [loop] = s.take_ready()
    s.open_loop(loop, [0, 1], concurrency=2, stop_on_error=True)
    x0, x1 = s.take_ready()
    s.succeed(x0, {"v": "x" * 1_000})
    s.succeed(x1, {"v": "x" * 1_000})
    [sp] = s.take_spills()
    assert (sp.which, sp.owner.scope) == ("r", (("l", 0),))


def test_an_inline_item_list_is_claimed_and_the_loop_carries_on_over_it() -> None:
    """The list is the largest container: it's claimed, the loop waits for its claim, then reads items by handle."""
    g = G().node("l", LOOP, {"items": [1]}).node("x", ECHO).edge("l", "x", "body")
    s = started(g)
    [loop] = s.take_ready()
    items = [f"{i:04d}" + "i" * 200 for i in range(10)]
    s.open_loop(loop, items, concurrency=1, stop_on_error=True)
    [sp] = s.take_spills()
    assert (sp.which, sp.owner, sp.entry["value"]) == ("i", loop, items)
    [x] = s.take_ready()  # its first iteration opened before: its item is inline
    assert s.scopes[x.scope].item == items[0]
    s.succeed(x, {})
    [c] = s.take_collects()
    s.collected(c.loop, c.index, 0)
    assert s.take_ready() == []  # it waits for its claim
    land(s, [sp])
    [x] = s.take_ready()
    assert s.scopes[x.scope].item == ClaimRef(sp.entry["id"], "/1").to_json()
    assert s.live == s.recount() <= BUDGET


def test_a_loop_over_a_claimed_list_is_a_cursor_and_its_batches_are_slices() -> None:
    """No item list is ever built: a count, and each item a handle into the list's claim (§5.3, pending work is
    cursors). A batch carries its slice the same way."""
    g = G().node("l", LOOP, {"items": [1]}).node("x", ECHO).edge("l", "x", "body")
    s = started(g)
    [loop] = s.take_ready()
    listed = ClaimRef("00000000-0000-4000-8000-000000000007")
    s.open_loop(loop, S.ItemsRef(listed.to_json(), 250), concurrency=1, stop_on_error=True, batch=100)
    [b] = s.take_batches()
    assert (b.start, b.items) == (0, S.ItemsRef(listed.to_json(), 100, 0))
    child = Scheduler(program(g), budget=Budget(100, root=False), prefix="t:1:run:2/batch")
    child.start_batch(loop.step, [S.OuterScope((), {})], S.ItemsRef(listed.to_json(), 50, 200), offset=200,
                      concurrency=1, stop_on_error=True)  # fmt: skip
    [x] = child.take_ready()
    assert child.scopes[x.scope].item == listed.extend(200).to_json()


def test_a_frozen_scope_item_is_claimed_and_read_by_handle() -> None:
    """In a batch child, an enclosing iteration's item is the child's to hold: a container like any other."""
    g = G().node("o", LOOP, {"items": [1]}).node("m", LOOP, {"items": [1]}).node("x", ECHO)
    g.edge("o", "m", "body").edge("m", "x", "body")
    s = Scheduler(program(g), budget=Budget(10, root=False), prefix="t:1:run:2/batch")
    big = "o" * 2_100
    outer = [S.OuterScope((), {}), S.OuterScope((("o", 0),), {}, big, 0)]
    s.start_batch(s.program.by_key["m"], outer, [1, 2], offset=0, concurrency=1, stop_on_error=True)
    [sp] = s.take_spills()
    assert (sp.which, sp.owner.scope, sp.entry["value"]) == ("t", (("o", 0),), big)
    land(s, [sp])
    assert s.scopes[(("o", 0),)].item == ClaimRef(sp.entry["id"]).to_json()


def test_the_variables_are_claimed_and_read_by_handle() -> None:
    g = G().node("a", ECHO)
    g.settings["vars_schema"] = {
        "type": "object",
        "properties": {"x": {"type": "string", "default": ""}, "y": {"type": "string", "default": ""}},
    }
    s = Scheduler(program(g), prefix="t:1:run:2")
    s.init_vars({"x": "x" * 2_500, "y": "short"})
    s.start()
    [sp] = s.take_spills()
    assert sp.which == "v"
    land(s, [sp])
    head = ClaimRef(sp.entry["id"])
    assert s.vars == {"x": head.extend("x").to_json(), "y": head.extend("y").to_json()}


def test_an_undo_record_is_claimed_and_its_version_read_by_handle() -> None:
    """A queued loop step names version 0; the write after it keeps what it replaced, and that record, the largest
    container now, is claimed: the step reads the old value through it."""
    g = G().node("o", LOOP, {"items": [1]}).node("i", LOOP, {"items": [1]}).node("e", ECHO)
    g.node("w", SET, {"assignments": {"x": "new"}}).edge("o", "i", "body").edge("i", "e", "body")
    g.settings["vars_schema"] = {"type": "object", "properties": {"x": {"type": "string", "default": ""}}}
    s = Scheduler(dataclasses.replace(program(g), open_scopes_cap=1), prefix="t:1:run:2")
    s.init_vars({"x": "o" * 1_500})
    s.start()
    assert s.take_spills() == []
    o, w = sorted(s.take_ready(), key=lambda i: name(s, i))
    s.open_loop(o, [0, 1], concurrency=2, stop_on_error=True)
    s.take_ready()  # `o:0/i` starts; `o:1/i` waits, naming version 0
    s.set_variables({"x": "n" * 1_500}, w)
    s.succeed(w, {})
    [sp] = s.take_spills()
    assert (sp.which, sp.entry["value"]) == ("u", {"x": ["o" * 1_500]})
    land(s, [sp])
    inner = Instance((("o", 0),), s.program.by_key["i"])
    s.consume_capture(inner)
    s.open_loop(inner, [], concurrency=1, stop_on_error=True)
    [c] = s.take_collects()
    s.collected(c.loop, c.index, None)
    [later] = s.take_ready()
    assert s.consume_capture(later) == {"x": ClaimRef(sp.entry["id"]).extend("x", 0).to_json()}


def test_a_snapshot_refuses_live_state_over_the_budget_until_its_claims_land() -> None:
    s = started(steps("a", "b", "c"))
    a, b, c, _ = s.take_ready()
    for inst in (a, b, c):
        s.succeed(inst, {"v": "x" * 800})
    s.take_settled()
    with pytest.raises(ValueError, match="live-state budget"):
        s.to_json()
    land(s, s.take_spills())
    restored = Scheduler.from_json(s.program, json.loads(json.dumps(s.to_json(check=True))), prefix="t:1:run:2")
    assert restored.live == s.live <= BUDGET
    assert restored.result_of(restored.scopes[()], "b") == s.result_of(s.scopes[()], "b")


def test_a_claim_given_back_unstarted_is_handed_out_again() -> None:
    s = started(steps("a", "b"))
    a, b, _ = s.take_ready()
    s.succeed(a, {"v": "x" * 1_500})
    s.succeed(b, {"v": "y" * 1_500})
    [sp] = s.take_spills()
    s.give_back([], [], [], [sp])  # drain mode left it unstarted: it waits again
    [again] = s.take_spills()
    assert again == sp


def test_a_frozen_scope_tells_a_claimed_result_from_a_missing_one() -> None:
    """A batch child's enclosing scopes: the parent says which results are in the claim, so a missing one stays
    missing, without a read."""
    g = G().node("a", ECHO).node("b", ECHO).node("l", LOOP, {"items": [1]}).node("x", ECHO)
    g.edge("a", "l").edge("l", "x", "body")
    s = Scheduler(program(g), budget=Budget(10, root=False), prefix="t:1:run:2/batch")
    head = ClaimRef("00000000-0000-4000-8000-000000000001").to_json()
    outer = [S.OuterScope((), {}, chain=head, claimed=S.claimed_codes(s.program, None, {"a"}))]
    s.start_batch(s.program.by_key["l"], outer, [1, 2], offset=0, concurrency=1, stop_on_error=True)
    root = s.scopes[()]
    assert s.result_of(root, "a") == ClaimRef(head["$claim"]).extend("a").to_json()
    assert s.result_of(root, "b") == {}
    assert size(head) <= S.HANDLE_MAX


def test_an_execution_isnt_quiescent_while_its_live_state_is_over_the_budget() -> None:
    from dewpoint.engine.runtime.execution import quiescent

    assert quiescent({}, {}, Budget(10, root=True), [], [], live=BUDGET)
    assert not quiescent({}, {}, Budget(10, root=True), [], [], live=BUDGET + 1)
    assert Instance((), S.NIL).step == S.NIL


class Claims:
    """The claims `claims.spill` would write: forwarding included, as the activity builds it."""

    def __init__(self) -> None:
        self.held: dict[str, Any] = {}

    def write(self, entry: dict[str, Any]) -> None:
        value = entry["value"]
        if entry.get("prev"):
            before = self.held[entry["prev"]]
            forward = {
                k: v if ClaimRef.of(v) else ClaimRef(entry["prev"], "/" + k).to_json() for k, v in before.items()
            }
            value = {**forward, **value}
        assert self.held.setdefault(entry["id"], value) == value  # written again: the same content
        self.held[entry["id"]] = value

    async def read(self, value: Any) -> Any:
        async def fetch(claim_id: str) -> StoredClaim:
            return StoredClaim(self.held[claim_id], ())

        return (await resolve_value(value, fetch)).value


@settings(
    max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture]
)
@given(st.data())
def test_random_claims_keep_every_result_and_variable_readable(data: st.DataObject) -> None:
    """Root results and a variable under a small budget; claims land in random order, around snapshots. In the end,
    every result and the variable read back, through handles, as what was stored."""
    S.LIVE_BUDGET = data.draw(st.sampled_from([400, 1_000, 2_500]), label="budget")
    keys = [f"r{k}" for k in range(8)]
    g = steps(*keys).node("w", SET, {"assignments": {"x": "w"}})
    g.settings["vars_schema"] = {"type": "object", "properties": {"x": {"type": "string", "default": ""}}}
    s = Scheduler(program(g), prefix="t:1:run:2")
    s.init_vars({"x": "v" * data.draw(st.sampled_from([0, 500]), label="var")})
    s.start()
    claims, out = Claims(), []
    expected: dict[str, Any] = {}
    running = [i for i in s.take_ready() if name(s, i) != "z"]
    while running or out:
        out += s.take_spills()
        assert s.live == s.recount()
        if data.draw(st.integers(0, 5), label="snapshot") == 0 and s.live <= S.LIVE_BUDGET:
            s.take_settled()
            s = Scheduler.from_json(s.program, json.loads(json.dumps(s.to_json(check=True))), prefix="t:1:run:2")
        if out and (not running or data.draw(st.booleans(), label="land")):
            sp = out.pop(data.draw(st.integers(0, len(out) - 1), label="which"))
            claims.write(sp.entry)
            s.spilled(sp.owner, sp.which, sp.first)
            continue
        inst = running.pop(data.draw(st.integers(0, len(running) - 1), label="step"))
        if name(s, inst) == "w":
            value = "n" * data.draw(st.sampled_from([10, 800]), label="write")
            s.set_variables({"x": value}, inst)
            expected["vars.x"] = value
            s.succeed(inst, {})
        else:
            expected[name(s, inst)] = {
                "output": {"v": name(s, inst) * data.draw(st.sampled_from([3, 300]), label="size")}
            }
            s.succeed(inst, expected[name(s, inst)]["output"])
    root = s.scopes[()]
    for key in keys:
        assert asyncio.run(claims.read(s.result_of(root, key))) == expected[key]
    if "vars.x" in expected:
        assert asyncio.run(claims.read(s.vars["x"])) == expected["vars.x"]
