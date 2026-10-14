# SPDX-License-Identifier: Apache-2.0
"""Sensitive literals are refused at publish (engine 2b spec §3.8): a value written into the workflow at a position a
schema marks sensitive — a node's config, a variable, a sub-flow's input — and a `default`, `enum`, `const` or
`examples` at a sensitive position of `input_schema` or `vars_schema`, nested or behind a local `$ref`. A secret comes
in through a run's input instead. Null and the empty string are literals too: §3.8 has no exemption. A sensitive
variable has no default: it's null until a step sets it, so its type must allow null."""

import uuid
from typing import Any

import pytest

from dewpoint.engine.graph.validate import _SENSITIVE_LITERAL, SubflowInfo, ValidationContext, validate
from dewpoint.plugins.flow import PLUGIN
from tests.engine.cel.support import nested_maps
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


@pytest.mark.parametrize(
    "token",
    [
        template("tok-1234"),  # a template of text alone is the literal it writes
        template("tok-", "1234"),
        template(""),
        cel('"tok-1234"'),  # a formula that reads nothing gives the same value every run: fn-1 is pure
        cel('"tok-" + "1234"'),
        cel('""'),
        cel('["tok-1234"].map(t, t)[0]'),  # its own variables aren't run data
        cel('["tok-1234"].map(trigger, trigger)[0]'),  # even named as a root
    ],
)
def test_a_template_or_formula_that_writes_a_fixed_value_is_refused(token: Any) -> None:
    g = G().node("s", SEND, {"token": token})
    assert diagnostics(g) == [("sensitive.literal", "/token")]


@pytest.mark.parametrize(
    "token",
    [
        cel('string == string ? "tok-1234" : ""'),  # nor are CEL's built-in types
        cel('type("") == .string ? "tok-1234" : ""'),
        cel('[int, uint, double, bool, bytes, list, map, null_type, type, dyn].size() > 0 ? "tok-1234" : ""'),
    ],
)
def test_a_formula_naming_types_writes_a_fixed_value_and_is_refused_for_both(token: Any) -> None:
    """A type's name isn't run data: the value is fixed, and refused as one; and a formula naming a type can't run."""
    g = G().node("s", SEND, {"token": token})
    assert sorted(set(diagnostics(g))) == [("cel.type_name", "/token"), ("sensitive.literal", "/token")]  # each name


@pytest.mark.parametrize(
    "token",
    [
        template("Bearer ", {"ref": "trigger.tok"}),
        template({"ref": "trigger.tok"}, "-1234"),
        template({"ref": "trigger.tok"}, "", {"ref": "trigger.tok"}, ":"),
    ],
)
def test_a_template_writing_text_beside_a_reference_is_refused(token: Any) -> None:
    """Its text is written into the workflow as it is, as a literal part of a sensitive object is: the validator can't
    tell a prefix from a secret, so it refuses both."""
    g = G().node("s", SEND, {"token": token})
    g.settings = {"input_schema": {"type": "object", "properties": {"tok": SECRET}, "required": ["tok"]}}
    assert diagnostics(g) == [("sensitive.literal", "/token")]


def test_a_formula_deeper_than_its_ast_decodes_is_invalid_at_a_sensitive_field() -> None:
    g = G().node("s", SEND, {"token": cel(nested_maps(17))})
    assert diagnostics(g) == [("cel.invalid", "/token")]


def test_a_template_of_references_and_a_formula_that_reads_the_run_are_fine() -> None:
    trigger = {"type": "object", "properties": {"tok": SECRET, "n": {"type": "integer"}}, "required": ["tok", "n"]}
    for token in (
        template({"ref": "trigger.tok"}),
        template("", {"ref": "trigger.tok"}, "", {"ref": "trigger.tok"}),  # empty text writes nothing
        cel("trigger.tok"),
        cel(".trigger.tok"),  # a root named from the top scope is read all the same
        cel("trigger.n > 0 ? trigger.tok : trigger.tok + trigger.tok"),
    ):
        g = G().node("s", SEND, {"token": token})
        g.settings = {"input_schema": trigger}
        assert diagnostics(g) == [], token


@pytest.mark.parametrize("value", [template("k3y-value"), cel('"k3y-" + "value"')])
def test_a_fixed_template_or_formula_assigned_to_a_sensitive_variable_is_refused(value: Any) -> None:
    g = G().node("v", SET, {"assignments": {"key": value}})
    g.settings = {"vars_schema": {"type": "object", "properties": {"key": {**SECRET, "type": ["string", "null"]}}}}
    assert diagnostics(g) == [("sensitive.literal", "/assignments/key")]


LOGIN = {"type": ["object", "null"], "properties": {"user": {"type": "string"}, "pw": SECRET}}
UNUSED_SECRET = {"$defs": {"unused": SECRET}}  # a sensitive definition no position reaches
LOGIN_VARS = {"type": "object", "properties": {"login": LOGIN}} | UNUSED_SECRET
LOGIN_BEHIND_REF = {"type": "object", "properties": {"login": {"$ref": "#/$defs/login"}}, "$defs": {"login": LOGIN}}
PLAIN_LOGIN_VARS = {"type": "object", "properties": {"login": {"type": ["object", "null"]}}} | UNUSED_SECRET


@pytest.mark.parametrize(
    ("value", "vars_schema", "refused"),
    [
        (ref("trigger.login", default={"user": "ops", "pw": "pa55word"}), LOGIN_VARS, True),
        (ref("trigger.login", default={"user": "ops"}), LOGIN_VARS, False),  # no sensitive part written
        (ref("trigger.login"), LOGIN_VARS, False),
        (cel('{"user": "ops", "pw": "pa55word"}'), LOGIN_VARS, True),
        (cel('{"user": "ops"}'), LOGIN_VARS, True),  # its parts aren't known at publish
        (cel('{"user": "ops"}'), LOGIN_BEHIND_REF, True),
        (cel('{"user": "ops"}'), PLAIN_LOGIN_VARS, False),  # an unused sensitive definition marks nothing here
    ],
)
def test_a_default_or_a_fixed_formula_holding_a_sensitive_part_is_refused(
    value: Any, vars_schema: dict[str, Any], refused: bool
) -> None:
    """A reference's default is a literal: refused where a literal is, at a part the schema marks. A formula that reads
    nothing can't be split into parts at publish, so it's refused wherever the schema marks one."""
    g = G().node("v", SET, {"assignments": {"login": value}})
    trigger = {"type": "object", "properties": {"login": {**LOGIN, "type": "object"}}, "required": ["login"]}
    g.settings = {"input_schema": trigger, "vars_schema": vars_schema}
    found = [d for d in diagnostics(g) if d[0] != "vars.no_default"]  # `login` isn't sensitive as a whole
    assert found == ([("sensitive.literal", "/assignments/login")] if refused else [])


@pytest.mark.parametrize(
    ("schema", "value", "refused"),
    [
        ({"type": ["array", "null"], "items": SECRET}, cel('["k3y-value"]'), True),
        ({"type": ["array", "null"], "prefixItems": [SECRET]}, cel('["k3y-value"]'), True),
        ({"type": ["object", "null"], "additionalProperties": SECRET}, cel('{"k": "k3y-value"}'), True),
        ({"type": ["object", "null"], "propertyNames": {"x-sensitive": True}}, cel('{"k3y-value": 1}'), True),
        ({"anyOf": [{"type": "null"}, LOGIN]}, cel('{"user": "ops"}'), True),
        ({"type": ["string", "null"], "not": {"type": "integer", "x-sensitive": True}}, cel('"plain"'), False),
        ({"type": ["string", "null"], "not": {"type": "integer", "x-sensitive": True}}, "plain", False),
    ],
)
def test_a_fixed_formula_is_refused_where_the_literal_rules_could_mark_a_part(
    schema: dict[str, Any], value: Any, refused: bool
) -> None:
    """The rules a literal is checked with (`marked_positions`): a part under a property, `additionalProperties`,
    `items` or a tuple position, a union's branch, or a map whose keys are sensitive. A keyword they don't read, as
    `not`, marks no part of the value."""
    g = G().node("v", SET, {"assignments": {"x": value}})
    g.settings = {"vars_schema": {"type": "object", "properties": {"x": {**schema, "default": None}}}}
    assert diagnostics(g) == ([("sensitive.literal", "/assignments/x")] if refused else [])


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
        ("input_schema", {"type": "object", "properties": {"login": {"x-sensitive": True, "$ref": "#/$defs/o"}},
                          "$defs": {"o": {"type": "object",
                                          "properties": {"pw": {"type": "string", "default": "pa55"}}}}},
         "/settings/input_schema/$defs/o/properties/pw"),  # nested in a definition a sensitive site reaches
    ],
)  # fmt: skip
def test_a_default_at_a_sensitive_position_is_refused(label: str, schema: dict[str, Any], field: str) -> None:
    g = G().node("s", SEND)
    g.settings = {label: schema}
    assert ("sensitive.default", field) in diagnostics(g)


def obj(**properties: Any) -> dict[str, Any]:
    return {"type": "object", "properties": properties}


@pytest.mark.parametrize("label", ["input_schema", "vars_schema"])
@pytest.mark.parametrize(
    ("schema", "field"),
    [
        (obj(key={**SECRET, "enum": ["k3y-one", "k3y-two"]}), "/properties/key/enum"),
        (obj(key={**SECRET, "const": "k3y-one"}), "/properties/key/const"),
        (obj(key={**SECRET, "examples": ["k3y-one"]}), "/properties/key/examples"),
        (obj(login={"type": "object", "x-sensitive": True, "properties": {"pw": {"type": "string", "enum": ["pa55"]}}}),
         "/properties/login/properties/pw/enum"),  # nested under a sensitive object
        (obj(login={"type": "object", "properties": {"pw": SECRET}, "examples": [{"pw": "pa55word"}]}),
         "/properties/login/examples"),  # an object literal with a sensitive part
        (obj(key={"anyOf": [SECRET, {"type": "string", "enum": ["k3y-one"]}]}),
         "/properties/key/anyOf/1/enum"),  # sensitive in one branch, sensitive in all
        (obj(key={"x-sensitive": True, "$ref": "#/$defs/k"})
         | {"$defs": {"k": {"type": "string", "enum": ["k3y-one"]}}},
         "/$defs/k/enum"),  # behind a local `$ref` from a sensitive site
        (obj(key={"$ref": "#/$defs/k"}) | {"$defs": {"k": {**SECRET, "const": "k3y-one"}}},
         "/$defs/k/const"),  # a sensitive definition
        (obj(login={"x-sensitive": True, "$ref": "#/$defs/login"})
         | {"$defs": {"login": obj(pw={"type": "string", "examples": ["pa55word"]})}},
         "/$defs/login/properties/pw/examples"),  # nested in a definition a sensitive site reaches
    ],
)  # fmt: skip
def test_an_enum_const_or_example_at_a_sensitive_position_is_refused(
    label: str, schema: dict[str, Any], field: str
) -> None:
    """They're literals in the published graph as a default is (§3.8), whatever the start form masks."""
    g = G().node("s", SEND)
    g.settings = {label: schema}
    assert diagnostics(g).count(("sensitive.literal", f"/settings/{label}{field}")) == 1


def test_an_enum_const_or_example_at_a_plain_position_is_fine() -> None:
    g = G().node("s", SEND)
    site = {"type": "string", "enum": ["a", "b"], "examples": ["a"]}
    g.settings = {"input_schema": obj(site=site, kind={"type": "string", "const": "ap"}, tok=SECRET)}
    assert diagnostics(g) == []


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


# ---- a constant a formula carries into a sensitive position (issue #79) ---------------------------------------------

STRINGS = {"type": "array", "items": {"type": "string"}}
RUN_DATA = {
    "type": "object",
    "properties": {
        "tok": SECRET, "pw": SECRET, "n": {"type": "integer"}, "x": {"type": "string"}, "s": {"type": "string"},
        "y": {"type": "string"}, "user": {"type": "string"}, "v": {"type": "string"}, "flag": {"type": "boolean"},
        "lst": {"type": "array", "items": {"type": "object"}}, "strs": STRINGS, "obj": {"type": "object"},
        "l": {"type": "array", "items": {"type": "integer"}}, "toks": {"type": "array", "items": SECRET},
        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["tok", "pw", "n", "s", "y", "user", "v", "flag", "lst", "strs", "obj", "l", "toks", "headers"],
}  # fmt: skip


def refusals(g: G, **ctx: Any) -> list[str | None]:
    """The fields refused as written secrets: other diagnostics (a type, a variable's default) aren't this rule's."""
    return [field for code, field in diagnostics(g, **ctx) if code == "sensitive.literal"]


def token(expr: str) -> list[str | None]:
    g = G().node("s", SEND, {"token": cel(expr)})
    g.settings = {"input_schema": RUN_DATA}
    return refusals(g)


def assigned(schema: dict[str, Any], value: Any) -> list[str | None]:
    g = G().node("v", SET, {"assignments": {"x": value}})
    g.settings = {"input_schema": RUN_DATA, "vars_schema": {"type": "object", "properties": {"x": schema}}}
    return refusals(g)


@pytest.mark.parametrize(
    "expr",
    [
        '"Bearer " + trigger.tok',  # the issue's four
        'trigger.n > 0 ? "s3cr3t-value" : ""',
        'has(trigger.x) ? "s3cr3t-value" : "s3cr3t-value"',
        'run.id != "" ? "s3cr3t-value" : ""',
        'trigger.n > 0 ? trigger.tok : ""',  # a fallback, as a reference's default
        "trigger.n > 0 ? trigger.tok : null",
        '["s3cr3t-value"].map(x, x)[0] + trigger.y',
        "string(4242) + trigger.tok",
        'sortedKeys(google.protobuf.Struct{fields: {"s3cr3t-value": trigger.tok}})[0]',  # the fresh review's High
    ],
)
def test_a_formula_carrying_a_written_constant_into_a_sensitive_position_is_refused(expr: str) -> None:
    assert token(expr) == ["/token"]


@pytest.mark.parametrize(
    "expr",
    [
        'trigger.headers["Authorization"]',  # a constant key or index looks a value up
        "trigger.toks[0]",
        'trigger.toks.filter(x, x.startsWith("api"))[0]',  # a constant in a predicate or a condition is compared
        'trigger.s == "api" ? trigger.tok : trigger.y',
        '"" + trigger.tok',  # empty text writes nothing
    ],
)
def test_a_formula_carrying_no_constant_into_it_publishes(expr: str) -> None:
    assert token(expr) == []


def test_the_refusal_quotes_nothing_the_formula_writes() -> None:
    g = G().node("s", SEND, {"token": cel('"s3cr3t-value" + trigger.tok')})
    g.settings = {"input_schema": RUN_DATA}
    found = [d for d in validate(g.build(), ValidationContext(catalog=CAT)).diagnostics
             if d.code == "sensitive.literal"]  # fmt: skip
    assert [d.message for d in found] == [_SENSITIVE_LITERAL] and "s3cr3t" not in repr(found)


NULLABLE_LOGIN = {**LOGIN, "default": None}
KEYS = {"type": ["object", "null"], "propertyNames": {"x-sensitive": True}, "default": None}
WHOLE_LOGIN = {**NULLABLE_LOGIN, "x-sensitive": True}


@pytest.mark.parametrize(
    ("schema", "expr", "refused"),
    [
        (NULLABLE_LOGIN, '{"user": "ops", "pw": trigger.pw}', False),  # a constant at a plain part
        (NULLABLE_LOGIN, '{"user": trigger.user, "pw": "pa55-" + trigger.pw}', True),
        ({"type": ["array", "null"], "items": SECRET, "default": None}, '[trigger.tok, "k3y-value"]', True),
        ({"type": ["array", "null"], "items": SECRET, "default": None}, 'trigger.toks + ["k3y-value"]', True),  # lost
        (KEYS, '{"k3y-value": trigger.v}', True),  # a written key where keys are marked
        (KEYS, "{trigger.v: trigger.s}", False),
        (KEYS, 'google.protobuf.Struct{fields: {"k3y-value": trigger.v}}', True),  # a Struct's fields are its keys
        (KEYS, '{"k3y-" + trigger.v: trigger.s}', True),  # a key computed from a constant
        (KEYS, '["k3y-value"].map(k, {k: trigger.v})[0]', True),
        (NULLABLE_LOGIN, '{"pw": trigger.pw}', False),  # a key whose value is marked isn't sensitive for that
        (WHOLE_LOGIN, '{"user": trigger.user, "pw": trigger.pw}', False),  # an object of reads: its keys are structure
    ],
)  # fmt: skip
def test_a_carried_constant_is_refused_where_it_lands_at_a_marked_part(
    schema: dict[str, Any], expr: str, refused: bool
) -> None:
    assert assigned(schema, cel(expr)) == (["/assignments/x"] if refused else [])


WHOLE_STRINGS = {**STRINGS, "type": ["array", "null"], "x-sensitive": True, "default": None}
WHOLE_OBJECT = {"type": ["object", "null"], "x-sensitive": True, "default": None}


@pytest.mark.parametrize(
    ("schema", "value", "refused"),
    [
        (WHOLE_STRINGS, cel("trigger.flag ? [] : trigger.strs"), True),  # written empties, as the literals are
        (WHOLE_OBJECT, cel("trigger.flag ? {} : trigger.obj"), True),
        (WHOLE_STRINGS, [], True),
        (WHOLE_STRINGS, cel("trigger.strs.map(x, x)"), False),
        (WHOLE_STRINGS, cel("[] + trigger.strs"), False),  # joined by `+`, an empty list writes nothing
    ],
)
def test_a_written_empty_list_or_map_is_written(schema: dict[str, Any], value: Any, refused: bool) -> None:
    """The owner's first plan review: `[]` and `{}` are container nodes, not constants, but written all the same."""
    assert assigned(schema, value) == (["/assignments/x"] if refused else [])


PW_OBJECT = {"type": ["object", "null"], "properties": {"pw": SECRET}}
TUPLE = {"type": ["array", "null"], "prefixItems": [PW_OBJECT], "default": None}
UNION = {
    "anyOf": [{"type": "object", "properties": {"y": PW_OBJECT}}, {"type": "object", "properties": {"z": {}}}],
    "default": None,
}


@pytest.mark.parametrize(
    ("schema", "at"), [(TUPLE, lambda v: [v]), (UNION, lambda v: {"y": v})], ids=["tuple", "union"]
)
@pytest.mark.parametrize(
    ("value", "refused"),
    [
        (cel('{"pw": "lit-" + trigger.s}'), True),  # a formula reading the run
        (cel('{"pw": "lit-value"}'), True),  # one reading nothing (#76's rule)
        (ref("trigger.obj", default={"pw": "lit-value"}), True),  # a reference's default
        ({"$value": {"kind": "literal", "value": {"pw": "lit-value"}}}, True),  # a literal envelope
        (cel('{"pw": trigger.pw}'), False),
        (ref("trigger.obj"), False),
    ],
    ids=["read-formula", "fixed-formula", "ref-default", "literal-envelope", "read-pw", "ref"],
)
def test_an_envelope_nested_at_a_tuple_position_or_in_a_union_is_checked_as_written_in_place(
    schema: dict[str, Any], at: Any, value: Any, refused: bool
) -> None:
    """The owner's first plan review and its siblings (ruling 6): `target_schema()` follows neither, so all four
    published clean while the same literal written in place was refused."""
    field = "/assignments/x/0" if schema is TUPLE else "/assignments/x/y"
    assert assigned(schema, at(value)) == ([field] if refused else [])


def test_a_map_of_reads_read_back_from_a_list_keeps_its_keys_structure() -> None:
    """Its keys may be at or under the value read (`ANY, KEY`): checked against keys a schema marks, never as values."""
    assert assigned(WHOLE_OBJECT, cel('trigger.lst.map(x, {"pw": trigger.pw})[0]')) == []


WHOLE_OBJECTS = {"type": ["array", "null"], "items": {"type": "object"}, "x-sensitive": True, "default": None}
PW_ITEMS = {"type": ["array", "null"], "items": PW_OBJECT, "default": None}
KEY_ITEMS = {"type": ["array", "null"], "items": {"type": "object", "propertyNames": {"x-sensitive": True}},
             "default": None}  # fmt: skip


@pytest.mark.parametrize("schema", [WHOLE_OBJECTS, PW_ITEMS], ids=["whole", "pw-items"])
@pytest.mark.parametrize(
    "value",
    [
        cel('[{"pw": trigger.pw}] + [{"pw": trigger.pw}]'),
        cel('trigger.lst.map(x, {"pw": trigger.pw})'),
        cel('[{"pw": trigger.pw}].filter(x, true)'),
        cel('trigger.lst.map(x, {"pw": trigger.pw}).map(y, y)'),
        [{"pw": ref("trigger.pw")}],  # the written list of references
    ],
)
def test_maps_of_reads_stay_structure_where_their_path_is_lost(schema: dict[str, Any], value: Any) -> None:
    """The owner's second plan review: a key keeps being a key through concatenation and the macros."""
    assert assigned(schema, value) == []


@pytest.mark.parametrize(
    ("schema", "expr"),
    [
        (KEY_ITEMS, 'trigger.lst.map(x, {"k3y-value": trigger.v})'),  # a written key where the items mark keys
        (KEY_ITEMS, '[google.protobuf.Struct{fields: {"k3y-value": trigger.v}}]'),
        (WHOLE_OBJECTS, '["x"].map(i, {"s3cr3t-value": trigger.v})[0].map(k, k)'),  # a written key, iterated: a value
        (WHOLE_OBJECTS, 'sortedKeys({"s3cr3t-value": trigger.v})'),
    ],
)
def test_a_written_key_is_refused_where_keys_are_marked_or_once_it_becomes_a_value(
    schema: dict[str, Any], expr: str
) -> None:
    assert assigned(schema, cel(expr)) == ["/assignments/x"]


def test_a_written_key_beside_a_reference_is_refused_where_keys_are_marked() -> None:
    """Ruling 7: a reference stands for a value, never for the key written beside it."""
    assert assigned(KEYS, {"k3y-value": ref("trigger.v")}) == ["/assignments/x"]  # the map whose keys are written


BOOLEAN = {"type": ["boolean", "null"], "x-sensitive": True, "default": None}


def test_a_macros_own_start_isnt_written_but_a_boolean_the_author_writes_is() -> None:
    assert assigned(BOOLEAN, cel("trigger.l.all(x, x > 0)")) == []
    assert assigned(BOOLEAN, cel("trigger.n > 0 ? true : false")) == ["/assignments/x"]


def test_a_carried_constant_into_a_sub_flows_sensitive_input_is_refused() -> None:
    child = uuid.UUID(int=9)
    info = SubflowInfo(child, uuid.UUID(int=10), {"type": "object", "properties": {"key": SECRET}}, {"type": "object"})
    g = G().node("r", RUN, {"workflow_id": str(child), "input": {"key": cel('"Bearer " + trigger.tok')}})
    g.settings = {"input_schema": RUN_DATA}
    assert refusals(g, subflows={child: info}) == ["/input/key"]
