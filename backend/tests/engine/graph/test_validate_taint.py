# SPDX-License-Identifier: Apache-2.0
"""The taint analysis at publish (engine 2b spec §4.1): every value site is marked tainted or not, per path read.

Sources: `x-sensitive` positions of `input_schema`, of a plugin's output schema and of `vars_schema`, and any position
a schema doesn't declare. Propagation: a reference, template or CEL value is tainted if any path it reads is; a
variable if its position is, or any assignment to it anywhere is; `item` takes its loop's element taint field by field,
`index` and `run.*` never; a loop's collected items take their `collect` value's taint and its count stays plain; a
sub-flow's outputs take the output-taint map recorded on its pinned version."""

import uuid
from typing import Any

from dewpoint.engine.graph.validate import SubflowInfo, ValidationContext, ValidationResult, validate
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G, cel, nid, ref, template
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
ECHO, LOOP, FILTER, SET = "testkit.echo@1", "flow.loop@1", "flow.filter@1", "flow.set_variables@1"
SECRET = {"type": "string", "x-sensitive": True}
ROWS = {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "card": SECRET},
                                  "required": ["id", "card"], "additionalProperties": False}}  # fmt: skip
INPUT = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "token": SECRET,
        "login": {"type": "object", "properties": {"user": {"type": "string"}, "pw": SECRET},
                  "required": ["user", "pw"], "additionalProperties": False},
        "rows": ROWS,
        "extra": {"type": "object"},
    },
    "required": ["name", "token", "login", "rows", "extra"],
    "additionalProperties": False,
}  # fmt: skip


def checked(g: G, **ctx: Any) -> ValidationResult:
    if "input_schema" not in g.settings:
        g.settings = {**g.settings, "input_schema": INPUT}
    result = validate(g.build(), ValidationContext(catalog=CAT, **ctx))
    assert result.ok, result.diagnostics
    return result


def tainted(result: ValidationResult) -> set[tuple[str | None, str]]:
    keys = {str(nid(k)): k for k in "abcdefghijklmnopqrstuvwxyz"}
    keys.update({str(nid(k)): k for k in ("loop", "set", "f", "r", "s", "t", "u", "v", "w")})
    return {(keys.get(n, n) if n else None, field) for n, field in result.tainted_sites}


def echoes(**values: Any) -> G:
    g = G()
    for key, value in values.items():
        g.node(key, ECHO, {"value": value})
    return g


def test_a_trigger_read_is_tainted_per_path() -> None:
    g = echoes(
        a=ref("trigger.token"),
        b=ref("trigger.name"),
        c=ref("trigger.login.user"),
        d=ref("trigger.login.pw"),
        e=ref("trigger.login"),
        f=ref("trigger.extra.anything", default=1),
    )
    result = checked(g)
    assert tainted(result) == {("a", "/value"), ("d", "/value"), ("e", "/value"), ("f", "/value")}


def test_cel_and_templates_are_tainted_when_anything_they_read_is() -> None:
    result = checked(echoes(a=cel("trigger.token + 'x'"), b=cel("size(trigger.name) > 3"),
                            c=template("Bearer ", {"ref": "trigger.token"}), d=template("hi ", {"ref": "trigger.name"}),
                            e=cel("size(trigger.rows) > 0"), f=cel("trigger.rows.map(r, r.id).size()"),
                            g=cel("run.id")))  # fmt: skip
    assert tainted(result) == {("a", "/value"), ("c", "/value"), ("e", "/value"), ("f", "/value")}


def test_a_variable_is_tainted_by_its_schema_or_by_any_assignment_even_a_later_one() -> None:
    g = echoes(a=ref("vars.plain"), b=ref("vars.marked"))
    g.node("set", SET, {"assignments": {"plain": ref("trigger.token")}}).edge("a", "set").edge("b", "set")
    g.settings = {"input_schema": INPUT, "vars_schema": {"type": "object", "properties": {
        "plain": {"type": "string", "default": ""}, "marked": SECRET}}}  # fmt: skip
    assert {("a", "/value"), ("b", "/value")} <= tainted(checked(g))
    g2 = echoes(a=ref("vars.plain"))
    g2.settings = {"input_schema": INPUT, "vars_schema": {"type": "object", "properties": {
        "plain": {"type": "string", "default": ""}}}}  # fmt: skip
    assert tainted(checked(g2)) == set()


def test_item_takes_its_loops_element_taint_field_by_field_and_index_never() -> None:
    g = G().node("loop", LOOP, {"items": ref("trigger.rows")})
    g.node("a", ECHO, {"value": ref("item.card")}).node("b", ECHO, {"value": ref("item.id")})
    g.node("c", ECHO, {"value": ref("index")})
    g.edge("loop", "a", "body").edge("loop", "b", "body").edge("loop", "c", "body")
    assert tainted(checked(g)) == {("loop", "/items"), ("a", "/value")}


def test_collected_items_take_their_collect_taint_and_the_count_stays_plain() -> None:
    g = G().node("loop", LOOP, {"items": ref("trigger.rows"), "collect": ref("item.card")})
    g.node("x", ECHO, {"value": ref("item.id")}).edge("loop", "x", "body")
    g.node("a", ECHO, {"value": ref("steps.loop.output.items")})
    g.node("b", ECHO, {"value": ref("steps.loop.output.count")})
    g.edge("loop", "a", "done").edge("loop", "b", "done")
    assert {("a", "/value")} <= tainted(checked(g)) and ("b", "/value") not in tainted(checked(g))


def test_a_filter_with_a_tainted_predicate_keeps_tainted_items_and_a_plain_count() -> None:
    g = G().node("f", FILTER, {"items": [1, 2, 3], "predicate": cel("size(trigger.token) > item")})
    g.node("a", ECHO, {"value": ref("steps.f.output.items")}).node("b", ECHO, {"value": ref("steps.f.output.count")})
    g.edge("f", "a").edge("f", "b")
    found = tainted(checked(g))
    assert ("a", "/value") in found and ("b", "/value") not in found


def test_a_transform_and_a_plugins_output_are_tainted_field_by_field() -> None:
    g = G().node("t", "flow.transform@1", {"fields": {"secret": ref("trigger.token"), "plain": ref("trigger.name")}})
    g.node("s", "testkit.sensitive@1")
    g.node("a", ECHO, {"value": ref("steps.t.output.secret")}).node("b", ECHO, {"value": ref("steps.t.output.plain")})
    g.node("c", ECHO, {"value": ref("steps.s.output.secret_value")})
    g.node("d", ECHO, {"value": ref("steps.s.output.public")})
    g.node("e", ECHO, {"value": ref("steps.s.output.login.password")})
    for k in "ab":
        g.edge("t", k)
    for k in "cde":
        g.edge("s", k)
    found = tainted(checked(g))
    assert {("a", "/value"), ("c", "/value"), ("e", "/value")} <= found
    assert not {("b", "/value"), ("d", "/value")} & found


def test_a_sub_flows_outputs_follow_its_versions_taint_map_and_unknown_counts_as_tainted() -> None:
    child = uuid.UUID(int=9)
    out = {"type": "object", "properties": {"key": {"type": "string"}, "other": {"type": "string"}}}

    def graph() -> G:
        g = G().node("r", "flow.run_workflow@1", {"workflow_id": str(child), "input": {}})
        g.node("a", ECHO, {"value": ref("steps.r.output.key", default="")})
        g.node("b", ECHO, {"value": ref("steps.r.output.other", default="")})
        return g.edge("r", "a").edge("r", "b")

    known = SubflowInfo(child, uuid.UUID(int=10), {"type": "object"}, out, output_taint={"key": True, "other": False})
    assert tainted(checked(graph(), subflows={child: known})) == {("a", "/value")}
    unknown = SubflowInfo(child, uuid.UUID(int=10), {"type": "object"}, out)
    assert tainted(checked(graph(), subflows={child: unknown})) == {("a", "/value"), ("b", "/value")}


def test_the_workflows_outputs_record_their_taint() -> None:
    g = echoes(a=1)
    g.settings = {"input_schema": INPUT, "outputs": {"secret": ref("trigger.token"), "plain": ref("trigger.name"),
                                                     "count": cel("size(trigger.rows)")}}  # fmt: skip
    result = checked(g)
    assert result.output_taint == {"secret": True, "plain": False, "count": True}
