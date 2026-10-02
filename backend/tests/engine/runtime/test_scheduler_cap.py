# SPDX-License-Identifier: Apache-2.0
"""The open-iteration cap and its reservation (engine 2b spec §5.3). An execution has at most `OPEN_SCOPES_CAP_v`
open iteration scopes, plus one reserved per nesting level for the progress path: the oldest open iteration at each
level. A loop step inside an iteration starts only when its loop can open an iteration at once; root-region loop steps
are never deferred; a batch-mode loop inside an iteration holds its slot until it ends. So open scopes never pass the
cap plus `D`, and the deepest iteration on the path can always progress: sibling loops can't starve it (§11.2)."""

import dataclasses
import json
from typing import Any

from dewpoint.engine.runtime.scheduler import BatchOutcome, Instance, Scheduler
from tests.engine.runtime.support import name, program
from tests.support.graphs import G

ECHO, LOOP = "testkit.echo@1", "flow.loop@1"


def capped(g: G, cap: int) -> Scheduler:
    s = Scheduler(dataclasses.replace(program(g), open_scopes_cap=cap))
    s.start()
    return s


def drive(s: Scheduler, items: dict[str, int], *, snapshot_every: int = 0, batches: bool = False) -> list[str]:
    """Run to the end, succeeding every step and collecting every iteration in the order the scheduler hands them
    over; a loop gets `items[key]` items (concurrency 10). Asserts the bound at every turn. `snapshot_every`: carry on
    from a snapshot every that many turns."""
    order: list[str] = []
    turn = 0
    queued_batches: list[Any] = []
    while s.ended is None:
        assert s.open_scopes <= s.cap + s.reserve, f"{s.open_scopes} open scopes, past {s.cap} + {s.reserve}"
        turn += 1
        if snapshot_every and turn % snapshot_every == 0:
            s.take_settled()
            s = Scheduler.from_json(s.program, json.loads(json.dumps(s.to_json(check=True))))
        ready, collects = s.take_ready(), s.take_collects()
        queued_batches += s.take_batches()
        if not ready and not collects and not queued_batches:
            raise AssertionError("stuck: nothing ready, nothing to collect, and the run hasn't ended")
        for inst in ready:
            order.append(name(s, inst))
            step = s.step(inst)
            if step.ref == LOOP:
                n = items[step.key]
                s.open_loop(inst, list(range(n)), concurrency=10, stop_on_error=True, batch=2 if batches else 0)
            else:
                s.succeed(inst, {})
        for c in collects:
            s.collected(c.loop, c.index, c.index)
        if not ready and not collects:
            b = queued_batches.pop(0)
            s.batch_done(b.loop, b.start, BatchOutcome(list(b.items), []))
    assert s.ended.status == "succeeded", s.ended
    return order


def nested(depth: int, siblings: int) -> G:
    """Loops `depth` deep; the innermost body holds `siblings` loops, each with an echo body."""
    g = G()
    parent: str | None = None
    for d in range(depth):
        g.node(f"l{d}", LOOP, {"items": [1]})
        if parent is not None:
            g.edge(parent, f"l{d}", "body")
        parent = f"l{d}"
    for k in range(siblings):
        g.node(f"s{k}", LOOP, {"items": [1]}).node(f"e{k}", ECHO).edge(parent, f"s{k}", "body")
        g.edge(f"s{k}", f"e{k}", "body")
    return g


def test_sibling_loops_in_nested_iterations_stay_within_the_cap_and_finish() -> None:
    """§11.2's counterexample: 24 sibling loops in nested 3 × 3 loops. A shared pool of D scopes deadlocks there."""
    g = nested(2, 24)
    items = {"l0": 3, "l1": 3, **{f"s{k}": 2 for k in range(24)}}
    for cap in (1, 2, 5):
        s = capped(g, cap)
        assert s.reserve == 3
        drive(s, items)


def test_the_bound_holds_across_snapshots() -> None:
    g = nested(2, 6)
    items = {"l0": 3, "l1": 3, **{f"s{k}": 3 for k in range(6)}}
    drive(capped(g, 2), items, snapshot_every=3)


def test_a_loop_step_inside_an_iteration_starts_only_when_its_loop_can_open_one() -> None:
    """Cap 1, D 2: the outer loop's two iterations (one from the reservation) fill it; only the oldest iteration's
    inner loop starts, from its level's reserved scope. The other's waits, queued, holding nothing."""
    g = G().node("o", LOOP, {"items": [1]}).node("i", LOOP, {"items": [1]}).node("e", ECHO)
    g.edge("o", "i", "body").edge("i", "e", "body")
    s = capped(g, 1)
    [o] = s.take_ready()
    s.open_loop(o, [0, 1], concurrency=2, stop_on_error=True)
    assert [name(s, i) for i in s.take_ready()] == ["o:0/i"]
    assert s.open_scopes == 2
    s.open_loop(Instance((("o", 0),), s.program.by_key["i"]), [0], concurrency=1, stop_on_error=True)
    [e] = s.take_ready()
    assert name(s, e) == "o:0/i:0/e" and s.open_scopes == 3
    s.succeed(e, {})
    [c] = s.take_collects()
    s.collected(c.loop, c.index, 0)  # the inner loop ends, and so does the outer iteration 0
    [c] = s.take_collects()
    s.collected(c.loop, c.index, 0)
    assert [name(s, i) for i in s.take_ready()] == ["o:1/i"]  # now the next one starts


def test_root_region_loop_steps_are_never_deferred() -> None:
    g = G().node("a", LOOP, {"items": [1]}).node("b", LOOP, {"items": [1]}).node("x", ECHO).node("y", ECHO)
    g.edge("a", "x", "body").edge("b", "y", "body")
    s = capped(g, 1)
    assert sorted(name(s, i) for i in s.take_ready()) == ["a", "b"]


def test_a_batch_mode_loop_inside_an_iteration_holds_its_slot_until_it_ends() -> None:
    """It opens no scope of its own: without its slot, started loops wouldn't be bounded by the cap."""
    g = G().node("o", LOOP, {"items": [1]}).node("i", LOOP, {"items": [1]}).node("e", ECHO)
    g.edge("o", "i", "body").edge("i", "e", "body")
    s = capped(g, 1)
    [o] = s.take_ready()
    s.open_loop(o, [0, 1], concurrency=2, stop_on_error=True)
    [i0] = s.take_ready()
    s.open_loop(i0, list(range(150)), concurrency=1, stop_on_error=True, batch=100)
    [b] = s.take_batches()
    assert s.take_ready() == []  # iteration 1's inner loop waits: the batch holds the reserved slot
    s.batch_done(b.loop, b.start, BatchOutcome(list(b.items), []))
    [b] = s.take_batches()
    s.batch_done(b.loop, b.start, BatchOutcome(list(b.items), []))
    [c] = s.take_collects()
    s.collected(c.loop, c.index, 0)
    assert [name(s, i) for i in s.take_ready()] == ["o:1/i"]


def test_batches_of_sibling_loops_inside_iterations_finish() -> None:
    drive(capped(nested(2, 4), 1), {"l0": 2, "l1": 2, **{f"s{k}": 3 for k in range(4)}}, batches=True)
