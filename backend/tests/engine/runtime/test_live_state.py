# SPDX-License-Identifier: Apache-2.0
"""The live-state counter (engine 2b spec §5.3, component 5): every value a snapshot holds inline, the trigger aside,
counted at its compact JSON size as it enters the state and uncounted as it leaves: results and items of open scopes,
loops' item lists and what they collected, the variables and their undo records. It isn't stored: a restore counts
again, and the two agree (the property test checks it after every change)."""

import json
from typing import Any

from dewpoint.engine.runtime.scheduler import Failure, Scheduler
from tests.engine.runtime.support import program
from tests.support.graphs import G

ECHO, LOOP = "testkit.echo@1", "flow.loop@1"


def size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":")))


def test_the_live_state_counts_values_as_they_enter_and_leave() -> None:
    s = Scheduler(
        program(
            G().node("a", ECHO).node("l", LOOP, {"items": [1]}).node("x", ECHO).edge("a", "l").edge("l", "x", "body")
        )
    )
    s.start()
    assert s.live == s.recount() == size({})  # the variables, none yet
    [a] = s.take_ready()
    s.succeed(a, {"n": "abc"})
    assert s.live == size({}) + size({"output": {"n": "abc"}})
    [loop] = s.take_ready()
    s.open_loop(loop, ["p", "q"], concurrency=1, stop_on_error=False)  # its items, what it collects, its failures
    base = size({}) + size({"output": {"n": "abc"}}) + size(["p", "q"]) + size([None, None]) + size([])
    assert s.live == base + size("p")  # and the open iteration's item
    [x] = s.take_ready()
    s.fail(x, Failure("testkit.boom", "it broke"))  # the iteration fails: its scope goes, the failure stays
    assert (
        s.live
        == s.recount()
        == base + size([{"index": 0, "code": "testkit.boom", "message": "it broke"}]) - 2 + size("q")
    )
    [x] = s.take_ready()
    s.succeed(x, {"v": 1})
    [c] = s.take_collects()
    s.collected(c.loop, c.index, "done")
    assert s.live == s.recount()  # the loop ended: its own state left, its result entered the root scope
    assert s.ended is not None and s.live == size({}) + size({"output": {"n": "abc"}}) + size(
        {
            "output": {
                "items": [None, "done"],
                "failures": [{"index": 0, "code": "testkit.boom", "message": "it broke"}],
                "count": 2,
            }
        }
    )


def test_a_restore_counts_the_live_state_again() -> None:
    s = Scheduler(program(G().node("a", ECHO).node("b", ECHO).edge("a", "b")))
    s.init_vars({"x": "y" * 50})
    s.start()
    [a] = s.take_ready()
    s.succeed(a, {"blob": "z" * 300})
    s.take_settled()
    restored = Scheduler.from_json(s.program, json.loads(json.dumps(s.to_json(check=True))))
    assert restored.live == s.live == size({"x": "y" * 50}) + size({"output": {"blob": "z" * 300}})
