# SPDX-License-Identifier: Apache-2.0
"""Sensitive literals are refused at publish (engine 2b spec §3.8): a value written into the workflow at a position a
schema marks sensitive — a node's config, a variable, a sub-flow's input — and a `default` at a sensitive position of
`input_schema` or `vars_schema`. A secret comes in through a run's input instead. A sensitive variable needs no
default: it's null until a step sets it. A null or empty literal writes nothing."""

import uuid
from typing import Any

import pytest

from dewpoint.engine.graph.validate import SubflowInfo, ValidationContext, validate
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G, nid, ref, template
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
    ],
)
def test_a_literal_at_a_sensitive_config_position_is_refused(token: Any) -> None:
    g = G().node("s", SEND, {"token": token})
    g.settings = {"input_schema": {"type": "object", "properties": {"tok": {"type": "string"}}}}
    assert ("sensitive.literal", "/token") in diagnostics(g)


def test_a_reference_without_a_default_and_plain_literals_are_fine() -> None:
    g = G().node("s", SEND, {"token": ref("trigger.tok"), "detail": "plain text"})
    g.node("e", SEND, {"token": ref("trigger.tok", default="")})  # an empty default holds no secret
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
    ],
)  # fmt: skip
def test_a_default_at_a_sensitive_position_is_refused(label: str, schema: dict[str, Any], field: str) -> None:
    g = G().node("s", SEND)
    g.settings = {label: schema}
    assert ("sensitive.default", field) in diagnostics(g)


def test_a_sensitive_variable_needs_no_default_and_a_null_one_is_fine() -> None:
    g = G().node("s", SEND)
    g.settings = {"vars_schema": {"type": "object", "properties": {"key": SECRET, "other": {
        "type": ["string", "null"], "x-sensitive": True, "default": None}}}}  # fmt: skip
    assert diagnostics(g) == []


def test_sensitive_variables_still_check_their_other_defaults() -> None:
    g = G().node("s", SEND)
    g.settings = {"vars_schema": {"type": "object", "properties": {"plain": {"type": "string"}}}}
    assert ("vars.no_default", "/settings/vars_schema/properties/plain") in diagnostics(g)
    assert nid("s")  # the node exists: only the variable is at fault
