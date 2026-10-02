# SPDX-License-Identifier: Apache-2.0
"""`snapshot_format` 2 (engine 2b spec §5.3): one code per node and per edge in region order, indexes instead of ids,
and no stored queue. Restoring rebuilds what's queued from the node, edge and loop states; what was handed out
before the snapshot (a sleeping timer, a batch child, a collect) isn't handed out again."""

import json
from typing import Any

from dewpoint.engine.runtime.scheduler import SNAPSHOT_FORMAT, BatchOutcome, Scheduler
from tests.engine.runtime.support import name, program
from tests.support.graphs import G

ECHO, LOOP = "testkit.echo@1", "flow.loop@1"


def fork() -> Scheduler:
    """a → b, a → c, with `a` done: `b` and `c` are queued."""
    s = Scheduler(program(G().node("a", ECHO).node("b", ECHO).node("c", ECHO).edge("a", "b").edge("a", "c")))
    s.start()
    [a] = s.take_ready()
    s.succeed(a, {"n": 1})
    s.take_settled()
    return s


def again(s: Scheduler) -> Scheduler:
    """Continue-as-new: the snapshot, through JSON, restored (the workflow takes what settled first)."""
    s.take_settled()
    return Scheduler.from_json(s.program, json.loads(json.dumps(s.to_json(check=True))))


def test_a_snapshot_is_codes_in_region_order_and_holds_no_queue() -> None:
    s = fork()
    snap = s.to_json(check=True)
    assert snap["snapshot_format"] == SNAPSHOT_FORMAT == 2
    assert not {"ready", "collects", "batches"} & set(snap)
    [root] = snap["scopes"]
    members = s.program.regions[None].members
    assert [s.program.steps[m].key for m in members] == ["a", "b", "c"]
    assert root[2] == "drr"  # done, then two queued (running: handed out on the next take)
    assert root[3] == "ll"  # a→b, a→c: both live


def test_a_snapshot_names_steps_by_index_never_by_id() -> None:
    s = fork()
    text = json.dumps(s.to_json(check=True))
    assert not [k for k in s.program.steps if str(k) in text]


def test_restoring_rebuilds_the_queue() -> None:
    s = again(fork())
    assert sorted(name(s, i) for i in s.take_ready()) == ["b", "c"]


def test_a_step_handed_out_before_the_snapshot_is_not_handed_out_again() -> None:
    s = fork()
    b, c = s.take_ready()
    s = again(s)
    assert s.take_ready() == []  # both still run: a sleeping timer's wake time is in the execution's snapshot
    s.succeed(b, {})
    s.succeed(c, {})
    assert s.ended is not None and s.ended.status == "succeeded"


def loop_at(n: int, **kwargs: Any) -> tuple[Scheduler, Any]:
    s = Scheduler(program(G().node("l", LOOP, {"items": [1]}).node("x", ECHO).edge("l", "x", "body")))
    s.start()
    [loop] = s.take_ready()
    s.open_loop(loop, list(range(n)), concurrency=1, stop_on_error=True, **kwargs)
    return s, loop


def test_a_collect_handed_out_before_the_snapshot_is_not_handed_out_again() -> None:
    s, _ = loop_at(2)
    [x] = s.take_ready()
    s.succeed(x, {})
    [c] = s.take_collects()
    s = again(s)
    assert s.take_collects() == [] and s.take_ready() == []
    s.collected(c.loop, c.index, 10)
    assert [name(s, i) for i in s.take_ready()] == ["l:1/x"]


def test_a_collect_not_handed_out_is_rebuilt() -> None:
    s, loop = loop_at(2)
    [x] = s.take_ready()
    s.succeed(x, {})
    s = again(s)
    [c] = s.take_collects()
    assert (c.loop, c.index) == (loop, 0)


def test_a_batch_handed_out_before_the_snapshot_is_not_handed_out_again() -> None:
    s, loop = loop_at(150, batch=100)
    [b] = s.take_batches()
    s = again(s)
    assert s.take_batches() == []
    s.batch_done(loop, b.start, BatchOutcome(list(b.items), []))
    [b2] = s.take_batches()
    assert (b2.start, b2.items) == (100, list(range(100, 150)))


def test_a_batch_not_handed_out_is_rebuilt() -> None:
    s, loop = loop_at(150, batch=100)
    s = again(s)
    [b] = s.take_batches()
    assert (b.loop, b.start, b.items) == (loop, 0, list(range(100)))
