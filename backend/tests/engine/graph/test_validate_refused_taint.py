# SPDX-License-Identifier: Apache-2.0
"""Refused at publish (engine 2b spec §4.5): a timer computed from tainted data (its duration is visible in history),
a tainted `flow.fail` message, and a tainted value passed into a sub-flow's input where the child doesn't mark it
sensitive, so each version's own analysis stays true. A tainted CEL expression runs in the isolated evaluator, and its
stored record says why."""

import uuid
from typing import Any

from dewpoint.engine.graph.validate import SubflowInfo, ValidationContext, ValidationResult, validate
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G, cel, nid, ref
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
SECRET = {"type": "string", "x-sensitive": True}
LOGIN = {"type": "object", "properties": {"user": {"type": "string"}, "pw": SECRET}, "required": ["user", "pw"],
         "additionalProperties": False}  # fmt: skip
INPUT = {
    "type": "object",
    "properties": {"token": SECRET, "n": {"type": "integer"}, "when": {"type": "string", "x-sensitive": True},
                   "login": LOGIN},
    "required": ["token", "n", "when", "login"],
    "additionalProperties": False,
}  # fmt: skip
CHILD = uuid.UUID(int=9)


def check(g: G, **ctx: Any) -> ValidationResult:
    g.settings = {"input_schema": INPUT, **g.settings}
    return validate(g.build(), ValidationContext(catalog=CAT, **ctx))


def codes(result: ValidationResult) -> list[tuple[str, str | None]]:
    return [(d.code, d.field) for d in result.diagnostics]


def test_a_timer_from_tainted_data_is_refused() -> None:
    assert codes(check(G().node("d", "flow.delay@1", {"duration_s": cel("size(trigger.token)")}))) == [
        ("taint.timer", "/duration_s")
    ]
    assert codes(check(G().node("d", "flow.delay@1", {"duration_s": ref("trigger.n")}))) == []
    assert codes(check(G().node("w", "flow.wait_until@1", {"until": ref("trigger.when")}))) == [
        ("taint.timer", "/until")
    ]


def test_a_tainted_failure_message_is_refused() -> None:
    assert codes(check(G().node("f", "flow.fail@1", {"message": cel("'bad: ' + trigger.token")}))) == [
        ("taint.fail_message", "/message")
    ]
    assert codes(check(G().node("f", "flow.fail@1", {"message": cel("'bad: ' + string(trigger.n)")}))) == []


def child(input_schema: dict[str, Any]) -> dict[Any, SubflowInfo]:
    return {CHILD: SubflowInfo(CHILD, uuid.UUID(int=10), input_schema, {"type": "object"}, {})}


def runs(input_value: dict[str, Any]) -> G:
    return G().node("r", "flow.run_workflow@1", {"workflow_id": str(CHILD), "input": input_value})


def test_a_tainted_value_goes_only_into_a_childs_sensitive_field() -> None:
    plain = {"type": "object", "properties": {"key": {"type": "string"}}}
    marked = {"type": "object", "properties": {"key": SECRET}}
    assert codes(check(runs({"key": ref("trigger.token")}), subflows=child(plain))) == [
        ("taint.subflow_input", "/input/key")
    ]
    assert codes(check(runs({"key": ref("trigger.token")}), subflows=child(marked))) == []
    assert codes(check(runs({"key": ref("trigger.login.user")}), subflows=child(plain))) == []


def test_a_partly_tainted_value_needs_only_its_tainted_parts_marked() -> None:
    marks_pw = {"type": "object", "properties": {"login": LOGIN}}
    marks_nothing = {"type": "object", "properties": {"login": {**LOGIN, "properties": {
        "user": {"type": "string"}, "pw": {"type": "string"}}}}}  # fmt: skip
    assert codes(check(runs({"login": ref("trigger.login")}), subflows=child(marks_pw))) == []
    assert codes(check(runs({"login": ref("trigger.login")}), subflows=child(marks_nothing))) == [
        ("taint.subflow_input", "/input/login")
    ]


def test_a_tainted_expression_is_recorded_to_run_in_the_evaluator() -> None:
    g = G().node("a", "testkit.echo@1", {"value": cel("trigger.token + 'x'")})
    g.node("b", "testkit.echo@1", {"value": cel("string(trigger.n)")})
    records = {r.node: r for r in check(g).expressions}
    assert (records[str(nid("a"))].mode, records[str(nid("a"))].reason) == ("activity", "reads sensitive data")
    assert records[str(nid("b"))].mode == "local"
