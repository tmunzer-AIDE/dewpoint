# SPDX-License-Identifier: Apache-2.0
"""Captures (engine 2b spec §5.3): a loop step inside an iteration, the only step the open-iteration cap defers, reads
the variables as they were when it became ready. Every other step reads them when it starts. The scheduler keeps the
current variables, numbered versions (the defaults are version 0, and each root `set_variables` makes the next), and,
while a queued loop step names an older version, one undo record per write since: what the write replaced."""

import dataclasses
import json
from typing import Any

from dewpoint.engine.runtime.scheduler import Failure, Instance, RunEnd, Scheduler
from tests.engine.runtime.support import name, program
from tests.support.graphs import G

ECHO, LOOP, SET = "testkit.echo@1", "flow.loop@1", "flow.set_variables@1"
VARS = {"type": "object", "properties": {"x": {"type": "integer", "default": 0}}}


def graph() -> G:
    """Root: `o` loops over `i` (a loop step inside each iteration), and `w` writes `x`."""
    g = G().node("o", LOOP, {"items": [1]}).node("i", LOOP, {"items": [1]}).node("e", ECHO)
    g.node("w", SET, {"assignments": {"x": 5}}).edge("o", "i", "body").edge("i", "e", "body")
    g.settings["vars_schema"] = VARS
    return g


def started(cap: int) -> tuple[Scheduler, Instance]:
    s = Scheduler(dataclasses.replace(program(graph()), open_scopes_cap=cap))
    s.init_vars({"x": 0})
    s.start()
    o, w = sorted(s.take_ready(), key=lambda i: name(s, i))
    s.open_loop(o, [0, 1], concurrency=2, stop_on_error=True)
    return s, w


def write(s: Scheduler, w: Instance) -> None:
    s.set_variables({"x": 5}, w)
    s.succeed(w, {})


def inner(s: Scheduler, index: int) -> Instance:
    return Instance((("o", index),), s.program.by_key["i"])


def finish_iteration(s: Scheduler, index: int) -> None:
    """The inner loop of iteration `index` runs over nothing, so the iteration settles."""
    s.open_loop(inner(s, index), [], concurrency=1, stop_on_error=True)
    [c] = s.take_collects()
    s.collected(c.loop, c.index, None)


def again(s: Scheduler) -> Scheduler:
    s.take_settled()
    return Scheduler.from_json(s.program, json.loads(json.dumps(s.to_json(check=True))))


def test_a_root_write_while_a_loop_step_is_queued_isnt_seen_by_it() -> None:
    s, w = started(cap=1)
    assert [name(s, i) for i in s.take_ready()] == ["o:0/i"]  # `o:1/i` waits for a scope
    write(s, w)
    assert s.vars == {"x": 5}  # what a step reads at start
    assert s.consume_capture(inner(s, 0)) == {"x": 0}
    finish_iteration(s, 0)
    assert [name(s, i) for i in s.take_ready()] == ["o:1/i"]
    assert s.consume_capture(inner(s, 1)) == {"x": 0}  # the version it became ready under
    assert s.undo == {}  # no queued step names an older version now


def test_the_same_run_reads_the_same_with_a_cap_that_never_defers() -> None:
    reads: list[Any] = []
    for cap in (1, 100):
        s, w = started(cap)
        got = []
        for inst in s.take_ready():
            got.append(s.consume_capture(inst))
        write(s, w)
        finish_iteration(s, 0)
        for inst in s.take_ready():
            got.append(s.consume_capture(inst))
        reads.append(got)
    assert reads[0] == reads[1] == [{"x": 0}, {"x": 0}]


def test_root_region_loop_steps_and_other_steps_read_at_start() -> None:
    g = G().node("a", ECHO).node("r", LOOP, {"items": [1]}).node("e", ECHO).node("w", SET, {"assignments": {"x": 5}})
    g.edge("a", "r").edge("r", "e", "body")
    g.settings["vars_schema"] = VARS
    s = Scheduler(dataclasses.replace(program(g), open_scopes_cap=1))
    s.init_vars({"x": 0})
    s.start()
    a, w = sorted(s.take_ready(), key=lambda i: name(s, i))
    s.succeed(a, {})  # `r` becomes ready under version 0
    write(s, w)
    [r] = s.take_ready()
    assert s.consume_capture(r) is None  # it captured nothing: it reads the variables now
    assert s.vars == {"x": 5} and s.undo == {}


def test_a_write_keeps_what_it_replaced_only_while_a_queued_step_needs_it() -> None:
    s, w = started(cap=1)
    s.take_ready()
    write(s, w)
    assert s.undo == {0: {"x": [0]}}
    s.consume_capture(inner(s, 0))
    assert s.undo == {0: {"x": [0]}}  # `o:1/i` still names version 0
    finish_iteration(s, 0)
    [i1] = s.take_ready()
    s.consume_capture(i1)
    assert s.undo == {}


def test_a_write_with_no_queued_capture_keeps_nothing() -> None:
    s, w = started(cap=100)
    for inst in s.take_ready():
        s.consume_capture(inst)
    write(s, w)
    assert s.undo == {} and s.vars_version == 1


def test_a_queued_step_whose_scope_ends_lets_its_version_go() -> None:
    s, w = started(cap=1)
    s.take_ready()
    write(s, w)
    s.consume_capture(inner(s, 0))
    s.end(RunEnd("cancelled", Failure("cancelled", "The run was cancelled.")))
    assert s.undo == {}


def test_a_released_loop_step_given_back_keeps_its_capture() -> None:
    s, w = started(cap=1)
    [i0] = s.take_ready()
    s.give_back([i0], [], [])  # drain mode: it never started
    write(s, w)
    [i0] = s.take_ready()
    assert s.consume_capture(i0) == {"x": 0}


def test_captures_and_versions_survive_a_snapshot() -> None:
    s, w = started(cap=1)
    [i0] = s.take_ready()
    write(s, w)
    s = again(s)
    assert s.vars == {"x": 5} and s.vars_version == 1
    assert s.consume_capture(i0) == {"x": 0}  # handed out before the snapshot, not started
    finish_iteration(s, 0)
    assert [name(s, i) for i in s.take_ready()] == ["o:1/i"]
    assert s.consume_capture(inner(s, 1)) == {"x": 0}
