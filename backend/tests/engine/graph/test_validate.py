# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import timedelta
from typing import Any

from dewpoint.engine.graph.validate import (
    SubflowInfo,
    ValidationContext,
    ValidationResult,
    referenced_workflows,
    validate,
)
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G, cel, nid, ref, template
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
ECHO, IF, LOOP, SET = "testkit.echo@1", "flow.if@1", "flow.loop@1", "flow.set_variables@1"


def check(g: G, **ctx: Any) -> ValidationResult:
    return validate(g.build(), ValidationContext(catalog=CAT, **ctx))


def codes(g: G, **ctx: Any) -> list[str]:
    return [d.code for d in check(g, **ctx).diagnostics]


def test_linear_reference_is_available() -> None:
    g = G().node("a", ECHO, {"value": 1}).node("b", ECHO, {"value": ref("steps.a.output.value")}).edge("a", "b")
    result = check(g)
    assert result.ok and result.diagnostics == () and result.node_refs == (ECHO,)


def _diamond(consumer_value: Any) -> G:
    return (
        G()
        .node("c", IF, {"condition": True})
        .node("a", ECHO)
        .node("b", ECHO)
        .node("j", ECHO, {"value": consumer_value})
        .edge("c", "a", "true")
        .edge("c", "b", "false")
        .edge("a", "j")
        .edge("b", "j")
    )


def test_branch_reference_needs_a_default() -> None:
    assert codes(_diamond(ref("steps.a.output.value"))) == ["ref.conditional"]
    assert codes(_diamond(ref("steps.a.output.value", default=0))) == []
    assert codes(_diamond(ref("steps.c.output"))) == []  # the branch point itself always ran


def test_parallel_join_references_are_available() -> None:
    g = (
        G()
        .node("x", ECHO)
        .node("a", ECHO)
        .node("b", ECHO)
        .node("j", ECHO, {"value": [ref("steps.a.output.value"), ref("steps.b.output.value")]})
        .edge("x", "a")
        .edge("x", "b")
        .edge("a", "j")
        .edge("b", "j")
    )
    assert codes(g) == []


def test_error_port_references() -> None:
    def g(h_value: Any, b_value: Any = None) -> G:
        return (
            G()
            .node("a", ECHO, on_error="port")
            .node("b", ECHO, {"value": b_value})
            .node("h", ECHO, {"value": h_value})
            .edge("a", "b")
            .edge("a", "h", "error")
        )

    assert codes(g(ref("steps.a.error.code"), ref("steps.a.output.value"))) == []
    assert codes(g(ref("steps.a.output.value"))) == ["ref.conditional"]
    assert codes(g(None, ref("steps.a.error.code"))) == ["ref.conditional"]


def test_error_reference_needs_an_error_behaviour() -> None:
    g = G().node("a", ECHO).node("b", ECHO, {"value": ref("steps.a.error.message")}).edge("a", "b")
    assert codes(g) == ["ref.no_error_output"]
    g = G().node("a", ECHO, on_error="continue").node("b", ECHO, {"value": ref("steps.a.output.value")}).edge("a", "b")
    assert codes(g) == ["ref.conditional"]  # a failed step that continues has no output


def test_ordering_and_names() -> None:
    siblings = (
        G()
        .node("x", ECHO)
        .node("a", ECHO)
        .node("b", ECHO, {"value": ref("steps.a.output.value")})
        .edge("x", "a")
        .edge("x", "b")
    )
    assert codes(siblings) == ["ref.not_upstream"]
    assert codes(G().node("a", ECHO, {"value": ref("steps.nope.output")})) == ["ref.unknown_step"]
    assert codes(G().node("a", ECHO, {"value": ref("steps.a.output.value")})) == ["ref.not_upstream"]
    g = G().node("s", "testkit.sensitive@1").node("b", ECHO, {"value": ref("steps.s.output.nope")}).edge("s", "b")
    assert codes(g) == ["ref.unknown_field"]


def _loops(collect: Any, leaf_value: Any, after_value: Any = None) -> G:
    return (
        G()
        .node("outer", LOOP, {"items": [{"n": 1}], "collect": collect})
        .node("inner", LOOP, {"items": [1, 2]})
        .node("leaf", ECHO, {"value": leaf_value})
        .node("after", ECHO, {"value": after_value})
        .edge("outer", "inner", "body")
        .edge("inner", "leaf", "body")
        .edge("outer", "after", "done")
    )


def test_loop_scopes() -> None:
    assert codes(_loops(ref("steps.inner.output.count"), [ref("loop.item"), ref("loops.outer.item")])) == []
    assert codes(_loops(None, None, ref("loop.item"))) == ["ref.loop_outside"]
    assert codes(_loops(None, None, ref("steps.leaf.output.value"))) == ["ref.out_of_scope"]
    assert codes(_loops(ref("steps.leaf.output.value"), None)) == ["ref.out_of_scope"]
    assert codes(_loops(None, None, ref("steps.outer.output.count"))) == []


SITES = {
    "type": "object",
    "properties": {
        "sites": {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        }
    },
    "required": ["sites"],
}


def test_loop_item_is_typed_from_the_items_reference() -> None:
    def g(value: Any) -> G:
        b = G().node("l", LOOP, {"items": ref("trigger.sites")}).node("leaf", ECHO, {"value": value})
        b.edge("l", "leaf", "body").settings["input_schema"] = SITES
        return b

    assert codes(g(ref("loop.item.name"))) == []
    assert codes(g(ref("loop.item.nope"))) == ["ref.unknown_field"]


def test_type_mismatch() -> None:
    g = G().node("s", "testkit.sensitive@1").node("c", IF, {"condition": ref("steps.s.output.public")}).edge("s", "c")
    assert codes(g) == ["ref.type_mismatch"]


def test_literal_only_kinds_and_cel() -> None:
    computed = G().node("l", LOOP, {"items": [1], "concurrency": ref("vars.n", default=1)}).node("e", ECHO)
    assert codes(computed.edge("l", "e", "body")) == ["value.literal_only"]
    assert codes(G().node("f", "flow.filter@1", {"items": [1], "predicate": True})) == ["value.kind_not_allowed"]
    filtered = G().node("f", "flow.filter@1", {"items": [1], "predicate": ref("vars.x", default=True)})
    assert codes(filtered) == ["value.kind_not_allowed"]
    assert codes(G().node("f", "flow.filter@1", {"items": [1], "predicate": cel("item > 1")})) == ["cel.unavailable"]


def test_literal_config_is_validated() -> None:
    result = check(G().node("d", "flow.delay@1", {"duration_s": "soon"}))
    assert [(d.code, d.field) for d in result.diagnostics] == [("config.invalid", "/duration_s")]
    too_wide = G().node("l", LOOP, {"items": [1], "concurrency": 50}).node("e", ECHO).edge("l", "e", "body")
    assert codes(too_wide) == ["config.invalid"]


VARS = {"type": "object", "properties": {"count": {"type": "integer", "default": 0}}}


def _vars(g: G) -> G:
    g.settings["vars_schema"] = VARS
    return g


def test_variables() -> None:
    ok = G().node("s", SET, {"assignments": {"count": 1}}).node("b", ECHO, {"value": ref("vars.count")}).edge("s", "b")
    assert codes(_vars(ok)) == []
    assert codes(_vars(G().node("s", SET, {"assignments": {"count": "one"}}))) == ["config.invalid"]
    assert codes(_vars(G().node("s", SET, {"assignments": {"nope": 1}}))) == ["vars.undeclared"]
    in_loop = G().node("l", LOOP, {"items": [1]}).node("s", SET, {"assignments": {"count": 1}}).edge("l", "s", "body")
    assert codes(_vars(in_loop)) == ["vars.write_in_loop"]
    parallel = (
        G()
        .node("x", ECHO)
        .node("s1", SET, {"assignments": {"count": 1}})
        .node("s2", SET, {"assignments": {"count": 2}})
        .edge("x", "s1")
        .edge("x", "s2")
    )
    assert codes(_vars(parallel)) == ["vars.concurrent_writers"]
    exclusive = (
        G()
        .node("c", IF, {"condition": True})
        .node("s1", SET, {"assignments": {"count": 1}})
        .node("s2", SET, {"assignments": {"count": 2}})
        .edge("c", "s1", "true")
        .edge("c", "s2", "false")
    )
    assert codes(_vars(exclusive)) == []
    no_default = G().node("a", ECHO)
    no_default.settings["vars_schema"] = {"type": "object", "properties": {"x": {"type": "string"}}}
    assert codes(no_default) == ["vars.no_default"]


def test_settings_schemas_must_use_resolvable_local_refs() -> None:
    missing = G().node("a", ECHO)
    missing.settings["vars_schema"] = {"type": "object", "properties": {"x": {"$ref": "#/$defs/Missing", "default": 1}}}
    assert codes(missing) == ["settings.unresolvable_ref"]  # reported, never raised
    remote = G().node("a", ECHO)
    remote.settings["input_schema"] = {"type": "object", "properties": {"s": {"$ref": "https://example.com/s.json"}}}
    assert codes(remote) == ["settings.unresolvable_ref"]
    cyclic = G().node("a", ECHO)
    cyclic.settings["vars_schema"] = {
        "type": "object",
        "properties": {"x": {"$ref": "#/$defs/A", "default": 1}},
        "$defs": {"A": {"allOf": [{"$ref": "#/$defs/A"}]}},
    }
    assert codes(cyclic) == ["settings.unresolvable_ref"]
    data = G().node("a", ECHO)
    data.settings["vars_schema"] = {
        "type": "object",
        "properties": {"x": {"type": "object", "default": {"$ref": "literal data", "$id": "also data"}}},
    }
    assert codes(data) == []  # defaults are data, not schemas


def test_static_waits_must_fit_the_run_deadline() -> None:
    day = 86_400
    g = (
        G()
        .node("d1", "flow.delay@1", {"duration_s": 20 * day})
        .node("d2", "flow.delay@1", {"duration_s": 15 * day})
        .edge("d1", "d2")
    )
    assert codes(g) == ["wait.exceeds_deadline"]
    assert codes(g, max_run_duration=timedelta(days=40)) == []


W = uuid.UUID("0b0e7a52-3d6c-4a53-9b58-7c2f0d4a1e11")
V = uuid.UUID("5a2f1c3e-8d9b-4c7a-a6e5-2b1d0f9e8c77")
SUB = SubflowInfo(
    workflow_id=W,
    version_id=V,
    input_schema={
        "type": "object",
        "properties": {"site": {"type": "string"}},
        "required": ["site"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
        "additionalProperties": False,
    },
)


def _sub(input_: dict[str, Any]) -> G:
    return (
        G()
        .node("r", "flow.run_workflow@1", {"workflow_id": str(W), "input": input_})
        .node("b", ECHO, {"value": ref("steps.r.output.count")})
        .edge("r", "b")
    )


def test_subflow_pins_and_typing() -> None:
    result = check(_sub({"site": "paris"}), subflows={W: SUB})
    assert result.ok and result.subflow_pins == {str(nid("r")): str(V)}
    assert codes(_sub({}), subflows={W: SUB}) == ["config.invalid"]
    assert codes(_sub({"site": "paris"})) == ["subflow.unknown"]
    handler = _sub({"site": "x"})
    handler.settings["failure_handler"] = str(V)
    assert referenced_workflows(handler.build()) == {W, V}


def test_workflow_outputs_define_the_output_schema() -> None:
    g = G().node("a", ECHO, {"value": 1})
    g.settings["outputs"] = {"total": ref("steps.a.output.value"), "label": "fixed"}
    result = check(g)
    assert result.ok and result.output_schema["required"] == ["label", "total"]
    d = _diamond(None)
    d.settings["outputs"] = {"picked": ref("steps.a.output.value")}
    assert codes(d) == ["ref.conditional"]
    s = G().node("x", ECHO).node("a", ECHO).node("stop", "flow.stop@1").edge("x", "a").edge("x", "stop")
    s.settings["outputs"] = {"v": ref("steps.a.output.value")}
    assert codes(s) == ["ref.conditional"]  # `stop` may end the run before `a` finishes


def test_templates() -> None:
    assert codes(G().node("d", "flow.delay@1", {"duration_s": template("5")})) == ["template.not_string"]
    whole = template("failed: ", {"ref": "steps.s.output"})
    g = G().node("s", "testkit.sensitive@1").node("f", "flow.fail@1", {"message": whole}).edge("s", "f")
    assert codes(g) == ["template.part_not_scalar"]
    part = template("failed: ", {"ref": "steps.s.output.public"})
    ok = G().node("s", "testkit.sensitive@1").node("f", "flow.fail@1", {"message": part}).edge("s", "f")
    assert codes(ok) == []


def test_transform_output_is_typed_from_its_fields() -> None:
    def g(condition: Any) -> G:
        return (
            G()
            .node("s", "testkit.sensitive@1")
            .node("t", "flow.transform@1", {"fields": {"name": ref("steps.s.output.public"), "n": 3}})
            .node("c", IF, {"condition": condition})
            .edge("s", "t")
            .edge("t", "c")
        )

    assert codes(g(ref("steps.t.output.name"))) == ["ref.type_mismatch"]  # text into a boolean
    assert codes(g(ref("steps.t.output.nope"))) == ["ref.unknown_field"]
