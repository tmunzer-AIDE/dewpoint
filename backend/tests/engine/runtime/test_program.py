# SPDX-License-Identifier: Apache-2.0
"""A published version compiled for execution (spec §6), and the versions that can't be."""

import pytest

from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.program import ProgramError, compile_program
from tests.engine.runtime.support import MANIFESTS, expressions, program
from tests.support.graphs import G, cel, nid, ref


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
