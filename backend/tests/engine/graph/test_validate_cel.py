# SPDX-License-Identifier: Apache-2.0
"""CEL values in the validator: typed environment, references, guards, result types and stored records."""

from typing import Any

import pytest

from dewpoint.engine.cel import types as T
from dewpoint.engine.cel.record import ExpressionRecord, Projection
from dewpoint.engine.graph.validate import ValidationContext, ValidationResult, validate
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G, cel, nid, ref
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
ECHO, IF, LOOP, FILTER = "testkit.echo@1", "flow.if@1", "flow.loop@1", "flow.filter@1"
INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"mac": {"type": "string"}},
                "required": ["mac"],
                "additionalProperties": False,  # declared whole: an undeclared field would count as tainted
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "maybe": {"type": "array"},
        "site": {"type": "object"},
        "opt": {"type": "object", "properties": {"x": {"type": "object", "properties": {"y": {"type": "string"}}}}},
    },
    "required": ["events", "tags", "site"],
}


def check(g: G) -> ValidationResult:
    return validate(g.build(), ValidationContext(catalog=CAT))


def codes(g: G) -> list[str]:
    return [d.code for d in check(g).diagnostics]


def one(expr: str, target_type: str = ECHO, field: str = "value", **settings: Any) -> G:
    g = G().node("a", target_type, {field: cel(expr)})
    g.settings = {"input_schema": INPUT, **settings}
    return g


def declassify(*sites: tuple[str, str]) -> list[dict[str, str]]:
    """Entries for decisions over elements the schema leaves open: undeclared counts as tainted (2b §4.1, §4.3)."""
    return [{"node": str(nid(key)), "field": field} for key, field in sites]


def record(g: G) -> ExpressionRecord:
    [r] = check(g).expressions
    return r


def test_always_available_arrays_are_declared_as_typed_paths() -> None:
    r = record(one("trigger.events.map(e, e.mac) + trigger.tags"))
    assert r.declarations["trigger.events"] == T.LIST_OF_MAPS
    assert r.declarations["trigger.tags"] == T.LIST_OF_STRINGS
    assert "trigger.maybe" not in r.declarations and "trigger.site" not in r.declarations
    assert r.idents == ("trigger.events", "trigger.tags") and r.mode == "local"


def test_optional_arrays_stay_dyn_and_need_as_list() -> None:
    assert codes(one("trigger.maybe.map(x, x)")) == ["cel.unproven_list", "cel.conditional_ref"]
    assert codes(one("has(trigger.maybe) ? asList(trigger.maybe).map(x, x) : []")) == []


def test_schema_declared_optional_fields_need_a_guard() -> None:
    """Spec §4.3: a field the schema declares optional, or one under an optional ancestor, needs has()."""
    assert codes(one("trigger.opt.x.y == 'a'")) == ["cel.conditional_ref"] * 3  # opt, opt.x, opt.x.y
    assert codes(one("has(trigger.opt) && has(trigger.opt.x) && has(trigger.opt.x.y) && trigger.opt.x.y == 'a'")) == []
    assert codes(one("has(trigger.opt.x)")) == ["cel.conditional_ref"]  # reads trigger.opt, which may be missing
    assert codes(one("has(trigger.opt) && has(trigger.opt.x)")) == []
    messages = [d.message for d in check(one("trigger.opt == null")).diagnostics]
    assert messages == ["`trigger.opt` is optional in its schema, so it may be missing."]


NULLABLE: dict[str, Any] = {
    **INPUT,
    "properties": {
        **INPUT["properties"],
        "n": {"type": ["object", "null"], "properties": {"x": {"type": "string"}}, "required": ["x"]},
        "u": {  # pydantic's Optional[Model]
            "anyOf": [{"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}, {"type": "null"}]
        },
        "m": {"type": ["object", "null"], "properties": {"x": {"type": "string"}}},  # optional and nullable
    },
    "required": [*INPUT["required"], "n", "u"],
}


def nullable(expr: str) -> G:
    g = one(expr)
    g.settings["input_schema"] = NULLABLE
    return g


def test_fields_of_a_nullable_value_need_a_non_null_guard() -> None:
    """Checkpoint-4 ruling: the schema says the value may be null, and a field of null fails, so it needs a guard,
    as a reference to it needs a default. Reading the value itself is fine: null is a value."""
    assert codes(nullable("trigger.n.x == 'a'")) == ["cel.conditional_ref"]
    assert codes(nullable("trigger.u.x == 'a'")) == ["cel.conditional_ref"]
    assert codes(nullable("has(trigger.n.x)")) == ["cel.conditional_ref"]  # has() reads trigger.n
    assert codes(nullable("trigger.n == null")) == []
    for guarded in (
        "trigger.n != null && trigger.n.x == 'a'",
        "trigger.n == null ? '' : trigger.n.x",
        "trigger.n == null || trigger.n.x == 'a'",
        'trigger.u != null && trigger["u"].x == "a"',
    ):
        assert codes(nullable(guarded)) == [], guarded
    assert codes(nullable("trigger.m.x == 'a'")) == ["cel.conditional_ref"] * 3  # absent, null, and x absent
    assert codes(nullable("has(trigger.m) && trigger.m != null && has(trigger.m.x) && trigger.m.x == 'a'")) == []
    [d] = check(nullable("trigger.n.x == 'a'")).diagnostics
    assert (d.message, d.fix) == (
        "`trigger.n` may be null in its schema, so reading its fields fails when it is.",
        "Guard it with `trigger.n != null`.",
    )


def test_open_and_schemaless_data_needs_no_guard() -> None:
    """Fields the schema doesn't declare carry no promise: missing at run time is an evaluation_error."""
    assert codes(one("trigger.site.name == 'Paris'")) == []  # `site` is an open object
    g = one("trigger.body.a.b == 1")
    g.settings["input_schema"] = {"type": "object"}  # no schema at all
    assert codes(g) == []


def test_optional_fields_of_items_and_variables_need_a_guard() -> None:
    loose = {
        **INPUT,
        "properties": {**INPUT["properties"], "loose": {"type": "array", "items": INPUT["properties"]["opt"]}},
    }
    loose["required"] = [*INPUT["required"], "loose"]
    body = G().node("l", LOOP, {"items": ref("trigger.loose")}).node("e", ECHO, {"value": cel("item.x")})
    body.edge("l", "e", "body").settings = {"input_schema": loose, "declassify": declassify(("l", "/items"))}
    assert codes(body) == ["cel.conditional_ref"]
    v = G().node("a", ECHO, {"value": cel("vars.cfg.name")})
    v.settings = {
        "vars_schema": {
            "type": "object",
            "properties": {"cfg": {"type": "object", "properties": {"name": {"type": "string"}}, "default": {}}},
        }
    }
    assert codes(v) == ["cel.conditional_ref"]


def test_nullable_arrays_are_never_typed() -> None:
    """A null is a value CEL can't iterate. Typing only non-null paths matches the reference rule that a default
    replaces a missing *or* null value: neither side ever treats null as a list."""
    nullable = {**INPUT, "properties": {**INPUT["properties"], "n": {"type": ["array", "null"]}}}
    nullable["required"] = [*INPUT["required"], "n"]
    g = one("has(trigger.n) && trigger.n != null ? asList(trigger.n).size() : 0")
    g.settings["input_schema"] = nullable
    assert "trigger.n" not in record(g).declarations


def test_loop_items_through_a_reference_default_type_the_item() -> None:
    body = G().node("l", LOOP, {"items": ref("trigger.maybe", default=[])}).node("e", ECHO, {"value": cel("item")})
    body.edge("l", "e", "body").settings = {"input_schema": INPUT, "declassify": declassify(("l", "/items"))}
    assert codes(body) == [] and record(body).declarations["item"] == T.DYN


def test_iterating_an_object_needs_sorted_keys() -> None:
    assert codes(one("trigger.site.map(k, k)")) == ["cel.unproven_list"]  # dyn: can't prove it's a list
    assert codes(one("sortedKeys(trigger.site).map(k, trigger.site[k])")) == []


def test_projections_cover_what_each_root_reads() -> None:
    r = record(one("has(trigger.site.name) && trigger.site.id == 'x' && trigger.events.size() > 0"))
    assert r.projections == (
        Projection(("trigger", "site", "id"), False),
        Projection(("trigger", "site", "name"), True),
    )


def test_step_outputs_behind_branches_need_a_has_guard() -> None:
    def diamond(expr: str) -> G:
        return (
            G()
            .node("c", IF, {"condition": True})
            .node("a", ECHO)
            .node("b", ECHO)
            .node("j", ECHO, {"value": cel(expr)})
            .edge("c", "a", "true")
            .edge("c", "b", "false")
            .edge("a", "j")
            .edge("b", "j")
        )

    assert codes(diamond("steps.a.output.value")) == ["cel.conditional_ref"]
    assert codes(diamond("has(steps.a.output) ? steps.a.output.value : 0")) == []
    assert codes(diamond("steps.c.output")) == []  # the branch point itself always ran


def test_reference_diagnostics_match_refs() -> None:
    assert codes(one("steps.nope.output.x")) == ["ref.unknown_step"]
    assert codes(one("vars.nope")) == ["ref.unknown_var"]
    assert codes(one("steps.a.outputs")) == ["cel.bad_path"]
    assert codes(one("item")) == ["ref.loop_outside"]
    assert codes(one("loop.item")) == ["cel.unknown_name"]
    assert codes(one("nope + 1")) == ["cel.unknown_name"]
    assert codes(one("'a'.lowerAscii()")) == ["cel.unknown_function"]
    assert codes(one("1 +")) == ["cel.invalid"]


@pytest.mark.parametrize(
    ("bracket", "dotted"),
    [
        ('steps["nope"].output.x', "steps.nope.output.x"),
        ('steps["b"].output.value', "steps.b.output.value"),  # b can't reach a
        ('steps.b["output"].value', "steps.b.output.value"),
        ('trigger["opt"]["x"].y == "a"', "trigger.opt.x.y == 'a'"),  # optional fields need guards
        (  # bracket guards count as guards: only `y` is left unguarded on both sides
            'has(trigger.opt) && has(trigger["opt"].x) && trigger.opt["x"]["y"] == "a"',
            "has(trigger.opt) && has(trigger.opt.x) && trigger.opt.x.y == 'a'",
        ),
    ],
)
def test_a_key_written_in_brackets_is_checked_like_the_dotted_field(bracket: str, dotted: str) -> None:
    """Review finding: `steps["b"]` skipped the step checks (and `trigger["opt"]` the guards) that `steps.b` gets."""

    def graph(expr: str) -> G:
        return G().node("a", ECHO, {"value": cel(expr)}).node("b", ECHO)

    g, h = graph(bracket), graph(dotted)
    g.settings = h.settings = {"input_schema": INPUT}
    assert codes(g) == codes(h) != []


def test_a_bracket_key_and_its_dotted_field_are_one_projection() -> None:
    r = record(one('trigger["site"]["id"] == "x" && has(trigger.site.name)'))
    assert r.projections == (
        Projection(("trigger", "site", "id"), False),
        Projection(("trigger", "site", "name"), True),
    )


@pytest.mark.parametrize(
    "expr",
    [
        "steps[trigger.site.k].output.x",  # a step chosen at run time
        'steps["not a key"].output',  # no step key looks like that
        "steps.b[trigger.site.k]",  # output or error, chosen at run time
        "loops[trigger.site.k].item",
    ],
)
def test_steps_and_loops_take_keys_publish_can_check(expr: str) -> None:
    g = G().node("b", ECHO).node("a", ECHO, {"value": cel(expr)}).edge("b", "a")
    g.settings = {"input_schema": INPUT}
    assert codes(g) == ["cel.bad_path"]


def _with_b(expr: str) -> G:
    g = G().node("a", ECHO, {"value": cel(expr)}).node("b", ECHO)  # b can't reach a
    g.settings = {"input_schema": INPUT}
    return g


@pytest.mark.parametrize(
    "expr",
    [
        '[steps][0]["b"].output.value',  # review finding: published although b can't run before a
        '[trigger][0].opt.x.y == "a"',  # review finding: skipped the optional-field guards
        '{"s": steps}.s.b.output.value',
        "(true ? trigger : trigger).opt.x",
        "dyn(trigger).opt.x",
        "[trigger].map(t, t.opt.x).size() > 0",
        "[trigger].exists(t, has(t.opt))",
        "trigger.events.map(e, trigger.opt)[0].x",
        "[steps.b][0].output.value",
    ],
)
def test_a_reference_read_through_a_wrapper_is_refused(expr: str) -> None:
    """A list, a map, a condition, dyn() or a comprehension hides which path is read, so publish can't check it."""
    assert "cel.bad_path" in codes(_with_b(expr))


@pytest.mark.parametrize(
    "expr",
    [
        "trigger.events.map(e, e.mac).size() > 0",  # elements of a checked path are data
        "trigger.events[0].mac",
        "trigger.events.filter(e, e.mac != '').map(e, e.mac).size() > 0",
        "trigger.events.map(e, [e][0].mac).size() > 0",
        "sortedKeys(trigger.site).map(k, trigger.site[k]).size() > 0",
        "[1, 2][0] + {'a': 1}.a",
        "size(trigger) > 0 && 'x' in trigger.site",
        "[trigger.tags, trigger.tags].size()",  # wrapped, but never read through
    ],
)
def test_data_read_through_elements_stays_allowed(expr: str) -> None:
    assert codes(_with_b(expr)) == []


def test_data_keys_in_brackets_stay_allowed() -> None:
    """Keys that aren't field names, or chosen at run time, read data as before: open data carries no promise."""
    assert codes(one('trigger.site["content-type"] == "x" && trigger.site[trigger.site.k] == 1')) == []


def test_item_and_index_inside_loops_and_filter_predicates() -> None:
    body = (
        G()
        .node("l", LOOP, {"items": ref("trigger.events")})
        .node("e", ECHO, {"value": cel("item.mac + string(index)")})
    )
    body.edge("l", "e", "body").settings = {"input_schema": INPUT}
    assert codes(body) == []
    f = G().node("f", FILTER, {"items": ref("trigger.tags"), "predicate": cel("item.startsWith('a') && index < 3")})
    f.settings = {"input_schema": INPUT}
    assert codes(f) == []
    assert record(f).declarations["item"] == T.DYN


def test_result_type_is_checked_against_the_field() -> None:
    assert codes(one("1 + 1", IF, "condition")) == ["cel.type_mismatch"]
    assert codes(one("trigger.events.size() > 0", IF, "condition")) == []
    assert codes(one("b'x'")) == ["cel.non_json_result"]


def test_has_on_a_typed_path_is_rejected_only_when_the_path_is_typed() -> None:
    assert codes(one("has(trigger.events)")) == []  # a has() test alone never declares the path
    assert codes(one("has(trigger.events) && trigger.events.size() > 0")) == ["cel.has_on_typed_path"]


def test_nested_comprehensions_warn_about_the_budget_and_run_as_a_separate_step() -> None:
    g = one("trigger.events.map(e, trigger.tags.filter(t, t == e.mac))")
    result = check(g)
    assert [(d.code, d.severity) for d in result.diagnostics] == [("cel.iteration_budget", "warning")]
    assert result.ok and result.expressions[0].mode == "activity"


def test_records_are_sorted_and_round_trip() -> None:
    g = G().node("b", ECHO, {"value": cel("2")}).node("a", ECHO, {"value": cel("1")})
    result = check(g)
    assert [r.node for r in result.expressions] == sorted([str(nid("a")), str(nid("b"))])
    for r in result.expressions:
        assert ExpressionRecord.from_json(r.to_json()) == r


@pytest.mark.parametrize("expr", ["trigger.site.id == 'x'", "trigger.events.filter(e, e.mac != '').size()"])
def test_workflow_outputs_can_use_cel(expr: str) -> None:
    g = G().node("a", ECHO)
    g.settings = {"input_schema": INPUT, "outputs": {"o": cel(expr)}}
    [r] = check(g).expressions
    assert (r.node, r.field) == (None, "/settings/outputs/o")
