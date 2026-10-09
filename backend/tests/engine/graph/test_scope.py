# SPDX-License-Identifier: Apache-2.0
"""What a field can read (B6; 4c-2a rulings 4–7): the validator's own answers, per field."""

import uuid
from typing import Any

import pytest

from dewpoint.engine.graph.scope import FIND_FOUND, Entry, Scope, scope
from dewpoint.engine.graph.validate import ValidationContext
from dewpoint.plugins.flow import PLUGIN as FLOW
from dewpoint.plugins.mist import PLUGIN as MIST
from tests.engine.graph.test_validate_cel import SPELLINGS, holder
from tests.support.catalog import catalog
from tests.support.graphs import G, cel, nid, ref
from tests.support.plugins.testkit import TESTKIT

CTX = ValidationContext(catalog=catalog(FLOW, TESTKIT, MIST))
SITE_ID = "00000000-0000-4000-8000-000000000001"
INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "site": {"type": "string"},
        "note": {"type": ["string", "null"]},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"mac": {"type": "string"}, "ap-name": {"type": "string"}, "in": {"type": "string"}},
                "required": ["mac"],
            },
        },
        "secret": {"type": "string", "x-sensitive": True},
        # A nullable parent (`!= null` before its fields), and unions whose alternatives aren't all objects or all
        # lists (`type(…) == map`, `type(…) == list` before a field or an index).
        "owner": {"type": ["object", "null"], "properties": {"name": {"type": "string"}}, "required": ["name"]},
        "who": {
            "anyOf": [
                {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
                {"type": "string"},
            ]
        },
        "labels": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}]},
        "nothing": {"type": "null"},  # only null: "is there" is never true
    },
    "required": ["site", "events", "owner", "who", "labels", "nothing"],
}


def graph() -> G:
    """`c` reads everything upstream. `maybe` and the transform `t` run on one branch (`t` holds a public field and a
    sensitive one); `f` filters, `l` loops over `x`. `token` is a sensitive variable nothing sets."""
    g = (
        G().node("get", "testkit.echo@1", {"value": 1})
        .node("devices", "mist.site_devices.list@1", {"site_id": SITE_ID})
        .node("br", "flow.if@1", {"condition": True}).node("maybe", "testkit.echo@1", {"value": 1})
        .node("t", "flow.transform@1", {"fields": {"open": 1, "hidden": ref("trigger.secret")}})
        .node("c", "flow.if@1", {"condition": True})
        .node("f", "flow.filter@1", {"items": ref("trigger.events"), "predicate": cel("true")})
        .node("l", "flow.loop@1", {"items": ref("trigger.events")}).node("x", "testkit.echo@1", {"value": 1})
        .edge("get", "devices").edge("devices", "br").edge("br", "maybe", port="true").edge("maybe", "t")
        .edge("t", "c").edge("br", "c", port="false").edge("c", "f", port="true").edge("f", "l")
        .edge("l", "x", port="body")
    )  # fmt: skip
    variables = {"count": {"type": "integer", "default": 0}, "token": {"type": "string", "x-sensitive": True}}
    g.settings = {"input_schema": INPUT, "vars_schema": {"type": "object", "properties": variables}}
    return g


def at(node: str, field: str, **ask: str) -> Scope:
    return scope(graph().build(), CTX, nid(node), field, **ask)


def by_path(s: Scope) -> dict[str, Entry]:
    return {e.path: e for e in s.entries}


def test_lists_what_a_field_can_read() -> None:
    paths = set(by_path(at("c", "/condition")))
    assert {"trigger", "trigger.site", "trigger.events", "trigger.note", "trigger.secret", "vars.count"} <= paths
    assert {"steps.get.output", "steps.get.output.value", "steps.maybe.output", "steps.devices.output",
            "steps.devices.output.results", "steps.devices.output.total"} <= paths  # fmt: skip
    assert {"run.id", "run.started_at", "run.now"} <= paths
    assert not any(p.startswith(("steps.c.", "steps.f.", "steps.x.", "item", "index")) for p in paths)


def test_says_a_step_on_a_branch_may_be_missing() -> None:
    maybe = by_path(at("c", "/condition"))["steps.maybe.output"]
    assert maybe.missing and maybe.step == str(nid("maybe"))
    assert maybe.formula is not None and [g.cel() for g in maybe.formula.guards] == ["has(steps.maybe.output)"]


def test_tells_missing_from_null() -> None:
    entries = by_path(at("c", "/condition"))
    assert entries["trigger.note"].missing and entries["trigger.note"].nullable
    assert not entries["trigger.site"].missing and not entries["trigger.site"].nullable
    total = entries["steps.devices.output.total"]
    assert total.types == ("integer",) and total.nullable and not total.missing


def test_reads_a_device_name_through_the_list() -> None:
    first = by_path(at("c", "/condition", under="steps.devices.output.results[0]"))
    name = first["steps.devices.output.results[0].name"]
    assert name.types == ("string",) and name.missing and not name.sensitive and name.nameable
    assert name.formula is not None and name.formula.sensitive  # a formula reads the list whole, which isn't declared


def test_shows_a_key_a_reference_cant_name_disabled() -> None:
    event = by_path(at("c", "/condition", under="trigger.events[0]"))
    dashed = next(e for e in event.values() if e.name == "ap-name")
    assert not dashed.nameable and dashed.formula is None and not dashed.children
    assert event["trigger.events[0].mac"].nameable


def test_offers_no_formula_for_a_key_cel_cant_select() -> None:
    word = by_path(at("c", "/condition", under="trigger.events[0]"))["trigger.events[0].in"]
    assert word.nameable and word.formula is None  # a reference may name it; CEL can't select `in`


def test_item_is_the_filters_in_its_predicate_and_the_loops_in_its_body() -> None:
    assert {"item", "index"} <= set(by_path(at("f", "/predicate")))
    assert not {"item", "index"} & set(by_path(at("f", "/items")))
    body = set(by_path(at("x", "/value")))
    assert {"item", "index"} <= body and "loops.l.item" not in body  # `item` already is the loop's


def test_at_answers_one_path_or_the_validators_own_problem() -> None:
    mac = at("c", "/condition", at="trigger.events[0].mac")
    assert [e.path for e in mac.entries] == ["trigger.events[0].mac"] and mac.entries[0].missing
    unknown = at("c", "/condition", at="steps.nope.output")
    assert unknown.entries == () and unknown.problem is not None and unknown.problem.code == "ref.unknown_step"
    later = at("c", "/condition", at="steps.x.output")
    assert later.problem is not None and later.problem.code in ("ref.out_of_scope", "ref.not_upstream")


def test_finds_fields_by_name_within_its_bounds() -> None:
    names = at("c", "/condition", find="name")
    assert "steps.devices.output.results[0].name" in by_path(names)
    assert all("name" in e.name.casefold() for e in names.entries)
    many = at("c", "/condition", find="e")
    assert len(many.entries) <= FIND_FOUND


def test_stops_at_the_reference_length_limit() -> None:
    long = "k" * 200
    g = G().node("c", "flow.if@1", {"condition": True})
    deep = {"type": "object", "properties": {long: {"type": "object", "properties": {long: {"type": "object",
            "properties": {long: {"type": "string"}}}}}}}  # fmt: skip
    g.settings = {"input_schema": deep}
    second = scope(g.build(), CTX, nid("c"), "/condition", under=f"trigger.{long}.{long}")
    assert [e.nameable for e in second.entries] == [False]  # trigger + 3 × 201 characters is past 512


def test_says_why_there_is_no_scope() -> None:
    assert scope(graph().build(), CTX, uuid.uuid4(), "/condition").unavailable == (
        "This step isn't in the saved draft yet."
    )
    loop = G().node("a", "testkit.echo@1").node("b", "testkit.echo@1").edge("a", "b").edge("b", "a")
    assert scope(loop.build(), CTX, nid("a"), "/value").unavailable is not None  # a cycle stops the analysis


def test_says_why_a_variable_not_yet_set_cant_be_read() -> None:
    """A sensitive variable without a default is null until a step sets it; its type refuses null. No default and no
    guard can make that read valid, so the entry carries validation's own problem and offers no formula."""
    token = by_path(at("c", "/condition"))["vars.token"]
    assert token.problem is not None and token.problem.code == "vars.unassigned" and token.formula is None
    assert by_path(at("c", "/condition"))["vars.count"].problem is None


def test_an_availability_guard_reads_no_data() -> None:
    """`has(steps.t.output)` asks whether `t` ran (the run's shape), so a public field stays public beside a sensitive
    one."""
    under = by_path(at("c", "/condition", under="steps.t.output"))
    public, hidden = under["steps.t.output.open"], under["steps.t.output.hidden"]
    assert public.formula is not None and [g.cel() for g in public.formula.guards] == ["has(steps.t.output)"]
    assert not public.sensitive and not public.formula.sensitive
    assert hidden.sensitive and hidden.formula is not None and hidden.formula.sensitive


def test_tests_null_where_a_value_may_be_null_untyped_or_only_null() -> None:
    entries = by_path(at("c", "/condition"))
    assert entries["trigger.nothing"].formula.null_test  # type: ignore[union-attr]  # only null
    assert entries["trigger.note"].formula.null_test  # type: ignore[union-attr]  # may be null
    assert entries["steps.get.output.value"].formula.null_test  # type: ignore[union-attr]  # untyped
    assert not entries["trigger.site"].formula.null_test  # type: ignore[union-attr]
    assert not entries["steps.devices.output.results"].formula.null_test  # type: ignore[union-attr]  # `list != null`


@pytest.mark.parametrize("spelling", SPELLINGS)
def test_guards_a_value_that_may_not_be_an_object_whatever_its_spelling(spelling: str) -> None:
    g = G().node("c", "flow.if@1", {"condition": True})
    g.settings = {"input_schema": holder(SPELLINGS[spelling])}
    n = by_path(scope(g.build(), CTX, nid("c"), "/condition", under="trigger.variant"))["trigger.variant.n"]
    assert n.formula is not None and [x.cel() for x in n.formula.guards] == [
        "type(trigger.variant) == map",
        "has(trigger.variant.n)",
    ]
