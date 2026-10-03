# SPDX-License-Identifier: Apache-2.0
"""A published version compiled for execution (spec §6), and the versions that can't be."""

import dataclasses
import uuid

import pytest

from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import VersionData
from dewpoint.engine.runtime.execution import program_of
from dewpoint.engine.runtime.program import ProgramError, compile_program
from tests.engine.runtime.support import MANIFESTS, expressions, program
from tests.support.graphs import G, cel, nid, ref, template


def graph() -> G:
    g = G()
    g.settings = {"outputs": {"n": ref("steps.l.output.count", default=0)}}
    g.node("a", "testkit.echo@1", {"value": 1}, on_error="port")
    g.node("l", "flow.loop@1", {"items": [1], "collect": cel("item + 1")})
    g.node("x", "testkit.echo@1", {"value": ref("item")}).node("h", "testkit.echo@1")
    return g.edge("a", "l").edge("l", "x", "body").edge("l", "h", "done").edge("a", "h", "error")


def test_steps_know_their_edges_ports_and_region() -> None:
    p = program(graph())
    a, loop, x = (p.steps[nid(k)] for k in ("a", "l", "x"))
    assert [p.steps[s].key for s in sorted(p.steps, key=lambda s: p.steps[s].topo)] == ["a", "l", "h", "x"]
    assert (a.control, loop.control, a.region, x.region) == (False, True, None, loop.id)
    assert {port: [p.edges[i].target for i in ids] for port, ids in a.out.items()} == {
        "error": [nid("h")],
        "out": [nid("l")],
    }
    assert [pointer for pointer, _ in loop.values] == ["/collect"] and p.chain(x.region) == [loop.id, None]
    assert p.record(loop.id, "/collect").expr == "item + 1"


def test_a_version_this_build_cannot_run_is_refused() -> None:
    g = graph()
    with pytest.raises(ProgramError):  # a node type this build doesn't have
        compile_program(g.data(), {k: v for k, v in MANIFESTS.items() if k != "testkit.echo@1"}, expressions(g), "p")
    with pytest.raises(ProgramError, match="`l`: no expression record for /collect"):  # damaged: fail before any step
        compile_program(g.data(), MANIFESTS, [], CURRENT_CEL_PROFILE)
    g.settings["outputs"] = {"n": cel("has(steps.l.output) ? steps.l.output.count : 0")}
    records = [r for r in expressions(g) if r["node"] is not None]
    with pytest.raises(ProgramError, match="no expression record for /settings/outputs/n"):
        compile_program(g.data(), MANIFESTS, records, CURRENT_CEL_PROFILE)


def test_a_damaged_output_is_refused() -> None:
    """Checkpoint-2 finding: compile checked the outputs' CEL records but not their envelopes, so a malformed output
    compiled, and evaluating it later raised outside the run's handlers."""
    g = graph()
    records = expressions(g)
    g.settings["outputs"] = {"n": {"$value": {"kind": "ref", "path": 5}}}  # publish refuses this; a damaged row
    with pytest.raises(ProgramError, match="/settings/outputs/n"):
        compile_program(g.data(), MANIFESTS, records, CURRENT_CEL_PROFILE)


def test_a_program_carries_the_versions_it_pins() -> None:
    """2a-3b: the version publish pinned for each `run_workflow` node, in a fixed order, and the failure handler's."""
    g = graph()
    p = compile_program(g.data(), MANIFESTS, expressions(g), CURRENT_CEL_PROFILE, {"n2": "v2", "n1": "v1"}, "h1")
    assert (list(p.subflows.items()), p.failure_handler) == ([("n1", "v1"), ("n2", "v2")], "h1")
    assert (program(g).subflows, program(g).failure_handler) == ({}, None)


def test_a_loops_outer_reads_are_the_outside_steps_its_body_references() -> None:
    """2a-3b: a batch child gets only the enclosing results its loop's body (nested loops included) and `collect`
    read, by reference, template or CEL; everything when an expression reads `steps` whole."""
    g = G().node("a", "testkit.echo@1").node("b", "testkit.echo@1").node("c", "testkit.echo@1")
    g.node("d", "testkit.echo@1").node("unread", "testkit.echo@1")
    g.node("l", "flow.loop@1", {"items": [1], "collect": ref("steps.d.output")})
    g.node("x", "testkit.echo@1", {"value": ref("steps.a.output.value", default=0)})
    g.node("y", "testkit.echo@1", {"value": template({"ref": "steps.b.output.value"}, "!")})
    g.node("i", "flow.loop@1", {"items": [1]}).node("z", "testkit.echo@1", {"value": cel("steps.c.output.value + 1")})
    for src, dst in [("a", "b"), ("b", "c"), ("c", "d"), ("d", "unread"), ("unread", "l"), ("x", "y"), ("y", "i")]:
        g.edge(src, dst)
    g.edge("l", "x", "body").edge("i", "z", "body")
    p = program(g)
    assert p.outer_reads(p.by_key["l"]) == {"a", "b", "c", "d"}
    assert p.outer_reads(p.by_key["i"]) == {"c"}  # the inner loop's outside includes the outer body's steps
    whole = G().node("a", "testkit.echo@1").node("l", "flow.loop@1", {"items": [1]})
    whole.node("x", "testkit.echo@1", {"value": cel("size(steps) > 0")}).edge("a", "l").edge("l", "x", "body")
    p = program(whole)
    assert p.outer_reads(p.by_key["l"]) is None


def test_a_version_compiles_once_per_worker_process() -> None:
    """A workflow task's CPU (engine 2b spec §5.3): compiling a large version took most of a task, in the first task
    of every execution and every continue. A version is immutable, so its program is the same wherever it's compiled;
    one whose content differs (damaged) compiles again."""
    g = G().node("a", "testkit.echo@1", {"value": 1})
    data = VersionData(str(uuid.uuid4()), str(uuid.uuid4()), g.data(), expressions(g), CURRENT_CEL_PROFILE,
                       {"testkit.echo@1": MANIFESTS["testkit.echo@1"]})  # fmt: skip
    assert program_of(data) is program_of(data)
    other = dataclasses.replace(data, graph=G().node("b", "testkit.echo@1", {"value": 2}).data())
    assert program_of(other) is not program_of(data)
