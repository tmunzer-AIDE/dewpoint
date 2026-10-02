# SPDX-License-Identifier: Apache-2.0
"""Sensitive literals are refused at publish (engine 2b spec §3.8): a value written into the workflow at a position a
schema marks sensitive — a node's config, a variable, a sub-flow's input — and a `default` at a sensitive position of
`input_schema` or `vars_schema`. A secret comes in through a run's input instead. Null and the empty string are
literals too: §3.8 has no exemption. A sensitive variable has no default: it's null until a step sets it, so its type
must allow null."""

import uuid
from typing import Any

import pytest

from dewpoint.engine.graph.validate import SubflowInfo, ValidationContext, validate
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G, cel, nid, ref, template
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
SEND, SET, RUN = "testkit.ambiguous_send@1", "flow.set_variables@1", "flow.run_workflow@1"
SECRET = {"type": "string", "x-sensitive": True}


def diagnostics(g: G, **ctx: Any) -> list[tuple[str, str | None]]:
    return [(d.code, d.field) for d in validate(g.build(), ValidationContext(catalog=CAT, **ctx)).diagnostics]


@pytest.mark.parametrize(
    "token",
    [
        "tok-1234",  # written in the config
        {"$value": {"kind": "literal", "value": "tok-1234"}},
        ref("trigger.tok", default="tok-1234"),  # a reference's default is written too
        template({"ref": "trigger.tok", "default": "tok-1234"}),
        "",  # empty and null are written too
        None,
        ref("trigger.tok", default=""),
        ref("trigger.tok", default=None),
        template({"ref": "trigger.tok", "default": ""}),
    ],
)
def test_a_literal_at_a_sensitive_config_position_is_refused(token: Any) -> None:
    g = G().node("s", SEND, {"token": token})
    g.settings = {"input_schema": {"type": "object", "properties": {"tok": {"type": "string"}}}}
    assert ("sensitive.literal", "/token") in diagnostics(g)


def test_a_reference_without_a_default_and_plain_literals_are_fine() -> None:
    g = G().node("s", SEND, {"token": ref("trigger.tok"), "detail": "plain text"})
    g.settings = {"input_schema": {"type": "object", "properties": {"tok": SECRET}, "required": ["tok"]}}
    assert diagnostics(g) == []


def test_a_literal_assigned_to_a_sensitive_variable_is_refused() -> None:
    g = G().node("v", SET, {"assignments": {"key": "k3y-value"}})
    g.settings = {"vars_schema": {"type": "object", "properties": {"key": SECRET}}}
    assert ("sensitive.literal", "/assignments/key") in diagnostics(g)


def test_a_literal_into_a_sub_flows_sensitive_input_is_refused() -> None:
    child = uuid.UUID(int=9)
    info = SubflowInfo(child, uuid.UUID(int=10), {"type": "object", "properties": {"key": SECRET}}, {"type": "object"})
    g = G().node("r", RUN, {"workflow_id": str(child), "input": {"key": "k3y-value"}})
    assert ("sensitive.literal", "/input/key") in diagnostics(g, subflows={child: info})


@pytest.mark.parametrize(
    ("label", "schema", "field"),
    [
        ("input_schema", {"type": "object", "properties": {"tok": {**SECRET, "default": "tok-1234"}}},
         "/settings/input_schema/properties/tok"),
        ("input_schema", {"type": "object", "properties": {"login": {
            "type": "object", "properties": {"pw": SECRET}, "default": {"pw": "pa55word"}}}},
         "/settings/input_schema/properties/login"),
        ("vars_schema", {"type": "object", "properties": {"key": {**SECRET, "default": "k3y-value"}}},
         "/settings/vars_schema/properties/key"),
        ("input_schema", {"type": "object", "properties": {"tok": {**SECRET, "default": ""}}},
         "/settings/input_schema/properties/tok"),
        ("vars_schema", {"type": "object", "properties": {"key": {
            "type": ["string", "null"], "x-sensitive": True, "default": None}}},
         "/settings/vars_schema/properties/key"),  # a written default, even null: omit it instead
    ],
)  # fmt: skip
def test_a_default_at_a_sensitive_position_is_refused(label: str, schema: dict[str, Any], field: str) -> None:
    g = G().node("s", SEND)
    g.settings = {label: schema}
    assert ("sensitive.default", field) in diagnostics(g)


def test_a_sensitive_variable_has_no_default_and_is_null_until_a_step_sets_it() -> None:
    """Its type allows null, or every read comes after a step sure to have set it: otherwise a read could see null
    where its type says it can't be."""
    trigger = {"type": "object", "properties": {"tok": SECRET, "n": {"type": "integer"}}, "required": ["tok", "n"]}

    def graph(vars_schema: dict[str, Any], *, before: bool) -> G:
        g = G().node("v", SET, {"assignments": {"key": ref("trigger.tok")}})
        g.node("s", SEND, {"token": ref("vars.key")})
        (g.edge("v", "s") if before else g.edge("s", "v"))
        g.settings = {"input_schema": trigger, "vars_schema": {"type": "object", "properties": {"key": vars_schema}}}
        return g

    assert diagnostics(graph(SECRET, before=True)) == []
    assert diagnostics(graph(SECRET, before=False)) == [("vars.unassigned", "/token")]
    nullable = G().node("s", SEND)
    nullable.settings = {"vars_schema": {"type": "object", "properties": {"key": {**SECRET, "type": ["string", "null"]},
        "alt": {"anyOf": [SECRET, {"type": "null"}]}}}}  # fmt: skip
    assert diagnostics(nullable) == []


def test_a_sensitive_variable_set_on_one_branch_or_by_a_step_that_may_fail_isnt_set_after_it() -> None:
    trigger = {"type": "object", "properties": {"tok": SECRET, "n": {"type": "integer"}}, "required": ["tok", "n"]}
    vars_schema = {"type": "object", "properties": {"key": SECRET}}
    g = G().node("c", "flow.if@1", {"condition": cel("trigger.n > 1")})
    g.node("v", SET, {"assignments": {"key": ref("trigger.tok")}}).node("x", "testkit.echo@1", {"value": 1})
    g.node("s", SEND, {"token": ref("vars.key")})
    g.edge("c", "v", "true").edge("c", "x", "false").edge("v", "s").edge("x", "s")
    g.settings = {"input_schema": trigger, "vars_schema": vars_schema}
    assert ("vars.unassigned", "/token") in diagnostics(g)
    g = G().node("v", SET, {"assignments": {"key": ref("trigger.tok")}}, on_error="continue")
    g.node("s", SEND, {"token": ref("vars.key")}).edge("v", "s")
    g.settings = {"input_schema": trigger, "vars_schema": vars_schema}
    assert ("vars.unassigned", "/token") in diagnostics(g)


def test_sensitive_variables_still_check_their_other_defaults() -> None:
    g = G().node("s", SEND)
    g.settings = {"vars_schema": {"type": "object", "properties": {"plain": {"type": "string"}}}}
    assert ("vars.no_default", "/settings/vars_schema/properties/plain") in diagnostics(g)
    assert nid("s")  # the node exists: only the variable is at fault


def test_a_sensitive_object_built_from_references_writes_no_literal() -> None:
    login = {"type": ["object", "null"], "x-sensitive": True, "properties": {"user": {"type": "string"},
             "pw": {"type": "string"}}}  # fmt: skip
    trigger = {"type": "object", "properties": {"user": {"type": "string"}, "pw": SECRET}, "required": ["user", "pw"]}

    def assigns(value: Any) -> list[tuple[str, str | None]]:
        g = G().node("v", SET, {"assignments": {"login": value}})
        g.settings = {"input_schema": trigger, "vars_schema": {"type": "object", "properties": {"login": login}}}
        return diagnostics(g)

    assert assigns({"user": ref("trigger.user"), "pw": ref("trigger.pw")}) == []
    assert ("sensitive.literal", "/assignments/login") in assigns({"user": "ops", "pw": ref("trigger.pw")})
