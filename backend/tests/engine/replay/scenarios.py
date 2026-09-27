# SPDX-License-Identifier: Apache-2.0
"""The runs every build records as golden histories (spec §7).

2a-3a records what it can run: branches, joins, dead paths and switch; inline loops, filter and transform; every
error policy; variables and timers; stop, fail, simulation and the deadline; CEL through `cel.evaluate`. 2a-3b adds
batched loops, sub-flows and continue-as-new; 2a-3c adds local CEL and the yield-point timer."""

from dataclasses import dataclass, field
from typing import Any

from tests.support.graphs import G, cel, ref

ECHO, IF, SWITCH, LOOP = "testkit.echo@1", "flow.if@1", "flow.switch@1", "flow.loop@1"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"x": {"type": "integer"}, "names": {"type": "array", "items": {"type": "string"}}},
    "required": ["x", "names"],
}
TRIGGER: dict[str, Any] = {"x": 7, "names": ["ap-1", "sw-1", "ap-2"]}


@dataclass(frozen=True)
class Scenario:
    graph: G
    trigger: dict[str, Any] = field(default_factory=lambda: dict(TRIGGER))
    options: dict[str, Any] = field(default_factory=dict)  # RunInput fields


def _graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": outputs}
    return g


def _branches() -> G:
    g = _graph(side=cel("has(steps.yes.output) ? 'yes' : 'no'"), size=ref("steps.big.output.value", default="?"))
    g.node("c", IF, {"condition": cel("trigger.x > 5")}).node("yes", ECHO, {"value": 1}).node("no", ECHO, {"value": 2})
    g.node("j", ECHO, {"value": "joined"}).edge("c", "yes", "true").edge("c", "no", "false")
    g.edge("yes", "j").edge("no", "j")
    cases = [{"port": "small", "when": cel("trigger.x < 5")}, {"port": "big", "when": cel("trigger.x > 5")}]
    g.node("s", SWITCH, {"cases": cases}).node("small", ECHO).node("big", ECHO, {"value": "big"}).edge("j", "s")
    return g.edge("s", "small", "small").edge("s", "big", "big")


def _loops() -> G:
    g = _graph(doubled=ref("steps.l.output.items"), aps=ref("steps.f.output.items"), t=ref("steps.t.output"))
    g.node("l", LOOP, {"items": [1, 2, 3], "concurrency": 2, "collect": cel("item * 2")})
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    g.node("f", "flow.filter@1", {"items": ref("trigger.names"), "predicate": cel("item.startsWith('ap-')")})
    g.node("t", "flow.transform@1", {"fields": {"n": cel("size(steps.f.output.items)")}})
    return g.edge("l", "f", "done").edge("f", "t")


def _errors() -> G:
    g = _graph(port=ref("steps.p.error.code", default="none"), kept=ref("steps.l.output.failures", default=[]))
    g.node("r", "testkit.fail_n@1", {"failures": 2}).node("u", "testkit.reconcile@1")
    g.node("p", "testkit.ambiguous_send@1", {"outcome": "rejected"}, on_error="port").node("h", ECHO)
    g.node("c", "testkit.ambiguous_send@1", {"outcome": "rejected"}, on_error="continue").edge("p", "h", "error")
    g.node("l", LOOP, {"items": [0, 1], "on_item_error": "continue", "collect": ref("item")})
    g.node("b", "testkit.ambiguous_send@1", {"outcome": cel("item == 1 ? 'rejected' : 'sent'")})
    return g.edge("l", "b", "body")


def _variables_and_timers() -> G:
    g = _graph(count=ref("vars.count"))
    g.settings["vars_schema"] = {"type": "object", "properties": {"count": {"type": "integer", "default": 0}}}
    g.node("d", "flow.delay@1", {"duration_s": 86_400})
    g.node("s", "flow.set_variables@1", {"assignments": {"count": cel("trigger.x + 1")}})
    return g.edge("d", "s")


def _stop() -> G:
    g = _graph(n=1).node("l", LOOP, {"items": [1, 2]}).node("s", "flow.stop@1")
    return g.edge("l", "s", "body")


def _failed() -> G:
    g = _graph().node("a", ECHO, {"value": 1}).node("f", "flow.fail@1", {"message": "no, stop"})
    return g.edge("a", "f")


def scenarios() -> dict[str, Scenario]:
    return {
        "branches": Scenario(_branches()),
        "loops": Scenario(_loops()),
        "errors": Scenario(_errors()),
        "variables_and_timers": Scenario(_variables_and_timers()),
        "stop": Scenario(_stop()),
        "failed": Scenario(_failed()),
        "simulate": Scenario(
            _graph(v=ref("steps.a.output.value")).node("a", ECHO, {"value": 5}), options={"mode": "simulate"}
        ),
        "deadline": Scenario(
            _graph().node("d", "flow.delay@1", {"duration_s": 3 * 86_400}), options={"max_run_duration_s": 86_400}
        ),
    }
