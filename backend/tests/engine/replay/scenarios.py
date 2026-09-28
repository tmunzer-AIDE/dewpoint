# SPDX-License-Identifier: Apache-2.0
"""The runs every build records as golden histories (spec §7).

2a-3a records what it can run: branches, joins, dead paths and switch; inline loops, filter and transform; every
error policy; variables and timers; stop, fail, simulation and the deadline; CEL through `cel.evaluate`. 2a-3b adds
batched loops, sub-flows, the failure handler, grants, continue-as-new and drain mode; 2a-3c adds local CEL and the
yield-point timer. A scenario that runs sub-flows builds its graph against the recorder's store, which publishes
them first."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tests.apps.worker.harness import MemoryStore
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
    graph: G | Callable[[MemoryStore], G]  # a callable publishes the sub-flows it runs, then builds the graph
    trigger: dict[str, Any] = field(default_factory=lambda: dict(TRIGGER))
    options: dict[str, Any] = field(default_factory=dict)  # RunInput fields

    def build(self, store: MemoryStore) -> G:
        return self.graph(store) if callable(self.graph) else self.graph


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


def _batches() -> G:
    g = _graph(items=ref("steps.l.output.items"), failures=ref("steps.l.output.failures"))
    items = ["sent"] * 101 + ["rejected"]  # two batches: the second one's last item fails
    g.node("l", LOOP, {"items": items, "concurrency": 10, "on_item_error": "continue", "collect": ref("item")})
    g.node("b", "testkit.ambiguous_send@1", {"outcome": ref("item")})
    return g.edge("l", "b", "body")


def _doubler(store: MemoryStore) -> str:
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
        "outputs": {"double": ref("steps.t.output.double")},
    }
    g.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.n * 2")}})
    return str(store.publish(g))


def _broken(store: MemoryStore) -> str:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": {}}
    g.node("f", "flow.fail@1", {"message": "the sub-flow gave up"})
    return str(store.publish(g))


def _subflows(store: MemoryStore) -> G:
    g = _graph(double=ref("steps.r.output.double"), code=ref("steps.x.error.code", default="none"))
    g.node("r", "flow.run_workflow@1", {"workflow_id": _doubler(store), "input": {"n": ref("trigger.x")}})
    g.node("x", "flow.run_workflow@1", {"workflow_id": _broken(store)}, on_error="continue")
    return g


def _failure_handler(store: MemoryStore) -> G:
    handler = G()
    handler.settings = {"input_schema": {"type": "object"}, "outputs": {}}
    handler.node("h", ECHO, {"value": ref("trigger.error.code", default="?")})
    g = _failed()
    g.settings["failure_handler"] = str(store.publish(handler))
    return g


def _grants(store: MemoryStore) -> G:
    sub = G()
    sub.settings = {
        "input_schema": {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]},
        "outputs": {"n": ref("steps.k.output.count")},
    }
    sub.node("k", "flow.filter@1", {"items": ref("trigger.items"), "predicate": cel("item % 2 == 0")})
    g = _graph(kept=ref("steps.r.output.n"))
    g.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(sub)), "input": {"items": list(range(1_200))}})
    return g


def _continued() -> G:
    g = _graph(items=ref("steps.l.output.items"))
    g.node("l", LOOP, {"items": list(range(30)), "collect": ref("item")})
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    return g.node("d", "flow.delay@1", {"duration_s": 3_600})


def _drained(store: MemoryStore) -> G:
    g = _graph(count=ref("steps.l.output.count"), double=ref("steps.r.output.double"))
    g.node("l", LOOP, {"items": list(range(101)), "concurrency": 10})  # two batches: 100 and 1
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    g.node("r", "flow.run_workflow@1", {"workflow_id": _doubler(store), "input": {"n": 21}})
    return g.node("d", "flow.delay@1", {"duration_s": 3_600})


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
        "batches": Scenario(_batches()),
        "subflows": Scenario(_subflows),
        "failure_handler": Scenario(_failure_handler),
        "grants": Scenario(_grants),
        "continue_as_new": Scenario(_continued(), options={"checkpoint_events": 60}),
        "drain": Scenario(_drained, options={"drain_events": 40}),
    }
