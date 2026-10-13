# SPDX-License-Identifier: Apache-2.0
"""A single step's seed contract (S2; the simulation design §5.2): its reads as pointers, with the resolver's
obligations, normalized; and the seeds checked against it."""

import copy
from typing import Any

from dewpoint.engine.graph.seeds import (
    NOT_ALONE,
    SEED_ALIAS,
    SEED_INVALID,
    SEED_MISSING,
    SEED_UNKNOWN,
    SeedContract,
    check,
    contract,
)
from dewpoint.engine.graph.validate import ValidationContext, validate
from dewpoint.plugins.flow import PLUGIN as FLOW
from tests.support.catalog import catalog
from tests.support.graphs import G, cel, nid, ref, template
from tests.support.plugins.testkit import TESTKIT

CTX = ValidationContext(catalog=catalog(FLOW, TESTKIT))
ECHO, LOOP, FILTER, TRANSFORM = "testkit.echo@1", "flow.loop@1", "flow.filter@1", "flow.transform@1"
INPUT: dict[str, Any] = {  # closed objects: an undeclared key could be a secret, which would taint every read
    "type": "object",
    "properties": {
        "site": {"type": "string"},
        "note": {"type": ["string", "null"]},
        "secret": {"type": "string", "x-sensitive": True},
        "aps": {"type": "array", "items": {"type": "object", "properties": {"mac": {"type": "string"}},
                                           "required": ["mac"], "additionalProperties": False}},
        "owner": {"type": "object", "properties": {"name": {"type": "string"}, "tag": {"type": "string"}},
                  "required": ["name"], "additionalProperties": False},
    },
    "required": ["site", "aps", "secret", "owner"],
    "additionalProperties": False,
}  # fmt: skip


def graph() -> G:
    g = G()
    g.settings = {
        "input_schema": copy.deepcopy(INPUT),
        "vars_schema": {"type": "object", "properties": {"n": {"type": "integer", "default": 0}}},
    }
    return g


def of(g: G, key: str) -> SeedContract:
    """The contract of a draft that validates: a use the validator refuses would say nothing of the rule."""
    built = g.build()
    assert [d.code for d in validate(built, CTX).diagnostics if d.severity == "error"] == []
    return contract(built, CTX, nid(key))


def table(c: SeedContract) -> dict[str, tuple[Any, ...]]:
    return {
        e.pointer: (e.types, e.required, e.nullable, e.sensitive, tuple(h.text for h in e.holds)) for e in c.entries
    }


def test_refs_templates_and_cel_reads_are_entries_with_the_resolvers_obligations() -> None:
    fields = {
        "site": template("at ", {"ref": "trigger.site"}),
        "note": ref("trigger.note", default=None),
        "secret": ref("trigger.secret"),
        "n": cel("vars.n + 1"),
        "when": cel("run.now"),  # the run binds it: never a seed
    }
    g = graph().node("t", TRANSFORM, {"fields": fields})
    assert table(of(g, "t")) == {
        "/trigger/note": (("string",), False, True, False, ()),  # null is `nullable`, not a type
        "/trigger/secret": (("string",), True, False, True, ()),
        "/trigger/site": (("string",), True, False, False, ()),
        "/vars/n": (("integer",), True, False, False, ()),
    }


def test_a_read_through_an_index_is_the_whole_list_and_a_read_inside_another_is_the_outer_one() -> None:
    fields = {
        "first": ref("trigger.aps[0].mac", default=""),
        "name": ref("trigger.owner.name"),
        "owner": cel("trigger.owner"),
    }
    g = graph().node("t", TRANSFORM, {"fields": fields})
    rows = table(of(g, "t"))
    assert rows["/trigger/aps"][0] == ("array",) and rows["/trigger/owner"][4] == ("/name",)
    assert set(rows) == {"/trigger/aps", "/trigger/owner"}


def test_a_value_every_use_defaults_may_be_absent_or_null() -> None:
    """The strictest use wins (§5.2): `site` is always there, but every use here gives a default, so the person may
    leave it absent or null to see the default; one strict use makes it required, and null then fits only where the
    schema allows it."""
    defaulted = {"a": ref("trigger.site", default="HQ"), "b": template({"ref": "trigger.site", "default": "HQ"})}
    c = of(graph().node("t", TRANSFORM, {"fields": defaulted}), "t")
    assert table(c)["/trigger/site"] == (("string",), False, True, False, ())
    assert check(c, {}, ["/trigger/site"]) == [] and check(c, {"/trigger/site": None}, []) == []
    strict = of(graph().node("t", TRANSFORM, {"fields": {**defaulted, "c": cel("trigger.site")}}), "t")
    assert table(strict)["/trigger/site"] == (("string",), True, False, False, ())


def test_a_child_is_held_only_where_a_use_reads_it_strictly() -> None:
    fields = {"owner": cel("trigger.owner"), "name": ref("trigger.owner.name", default="?"),
              "tag": cel("has(trigger.owner.tag) ? trigger.owner.tag : ''")}  # fmt: skip
    rows = table(of(graph().node("t", TRANSFORM, {"fields": fields}), "t"))
    assert rows["/trigger/owner"][1:] == (True, False, False, ())  # neither `name` (defaulted) nor `tag` (guarded)
    strict = {**fields, "name": ref("trigger.owner.name")}
    assert table(of(graph().node("t", TRANSFORM, {"fields": strict}), "t"))["/trigger/owner"][4] == ("/name",)


def test_the_innermost_loops_item_is_canonical_and_its_alias_refused() -> None:
    g = graph().node("l", LOOP, {"items": ref("trigger.aps")})
    g.node("x", ECHO, {"value": {"a": ref("item.mac"), "b": ref("loops.l.index")}}).edge("l", "x", "body")
    c = of(g, "x")
    assert set(table(c)) == {"/item/mac", "/index"}
    assert c.aliases == {"/loops/l/item": "/item", "/loops/l/index": "/index"}
    problems = check(c, {"/loops/l/item": {"mac": "m"}, "/index": 0}, [])
    assert [(p.code, p.pointer) for p in problems] == [(SEED_MISSING, "/item/mac"), (SEED_ALIAS, "/loops/l/item")]
    [_, below] = check(c, {"/loops/l/item/mac": "m", "/index": 0}, [])  # a path below an alias is the alias's too
    assert (below.code, below.pointer) == (SEED_ALIAS, "/loops/l/item/mac") and "/item/mac" in below.message


def test_a_read_a_guard_proves_present_may_be_absent() -> None:
    """Spec §5.2: a guarded CEL read tolerates absence, of a value the schema says is always there too. A read below
    a guarded one is held only when the value is given."""
    c = of(graph().node("t", TRANSFORM, {"fields": {"s": cel("has(trigger.site) ? trigger.site : ''")}}), "t")
    assert table(c)["/trigger/site"] == (("string",), False, False, False, ())
    owner = cel("has(trigger.owner) ? trigger.owner.name : ''")
    o = of(graph().node("t", TRANSFORM, {"fields": {"n": owner}}), "t")
    assert table(o)["/trigger/owner"][1:] == (False, False, False, ("/name",))
    assert check(o, {}, ["/trigger/owner"]) == [] and [p.code for p in check(o, {"/trigger/owner": {}}, [])] == [
        SEED_INVALID
    ]


def test_a_value_is_checked_against_its_whole_schema_and_each_read_inside_it() -> None:
    """Merging a read into the outer one keeps its type: a child of the wrong type, or a list's element, is refused,
    and so is a variable read inside the variables given whole."""
    fields = {"owner": cel("trigger.owner"), "name": ref("trigger.owner.name"), "aps": cel("size(trigger.aps)")}
    c = of(graph().node("t", TRANSFORM, {"fields": fields}), "t")
    assert check(c, {"/trigger/owner": {"name": "n"}, "/trigger/aps": [{"mac": "m"}]}, []) == []
    found = check(c, {"/trigger/owner": {"name": 42}, "/trigger/aps": [{"mac": 5}]}, [])
    assert [(p.code, p.pointer) for p in found] == [(SEED_INVALID, "/trigger/aps"), (SEED_INVALID, "/trigger/owner")]
    assert found[1].message.startswith("At /name: ")
    v = of(graph().node("t", TRANSFORM, {"fields": {"k": cel("size(vars)"), "n": ref("vars.n")}}), "t")
    assert check(v, {"/vars": {"n": 1}}, []) == [] and [p.code for p in check(v, {"/vars": {"n": "x"}}, [])] == [
        SEED_INVALID
    ]


def test_inside_a_value_presence_and_null_come_from_the_uses_never_the_schemas_required() -> None:
    """§5.2: a read inside a value with a default tolerates its absence and null there, as the run does; its schema
    still types it. One strict read makes it a path the value must hold, not null."""
    defaulted = {"owner": cel("trigger.owner"), "name": ref("trigger.owner.name", default="?")}
    c = of(graph().node("t", TRANSFORM, {"fields": defaulted}), "t")
    assert check(c, {"/trigger/owner": {}}, []) == [] and check(c, {"/trigger/owner": {"name": None}}, []) == []
    assert [p.code for p in check(c, {"/trigger/owner": {"name": 42}}, [])] == [SEED_INVALID]
    strict = of(graph().node("t", TRANSFORM, {"fields": {**defaulted, "name": ref("trigger.owner.name")}}), "t")
    for owner in ({}, {"name": None}):
        assert [p.code for p in check(strict, {"/trigger/owner": owner}, [])] == [SEED_INVALID]
    v = of(graph().node("t", TRANSFORM, {"fields": {"k": cel("size(vars)"), "n": ref("vars.n", default=9)}}), "t")
    assert check(v, {"/vars": {"n": None}}, []) == [] and check(v, {"/vars": {}}, []) == []


def with_input(**fields: Any) -> G:
    """The test input, with `fields` added as required properties."""
    g = graph()
    g.settings["input_schema"]["properties"].update(fields)
    g.settings["input_schema"]["required"] += list(fields)
    return g


def test_presence_tested_by_a_schema_keeps_its_meaning() -> None:
    """`required` inside `not` or `if` is a test of the value, never an obligation excused away."""
    person = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "not": {"required": ["name", "age"]},
        "additionalProperties": False,
    }
    mode = {"type": "object", "properties": {"mode": {"type": "integer"}, "x": {}}, "if": {"required": ["mode"]},
            "then": {"properties": {"x": {"type": "integer"}}}, "else": {"properties": {"x": {"type": "string"}}},
            "additionalProperties": False}  # fmt: skip
    fields = {"p": cel("trigger.person"), "m": cel("trigger.mode")}
    c = of(with_input(person=person, mode=mode).node("t", TRANSFORM, {"fields": fields}), "t")
    assert check(c, {"/trigger/person": {"name": "n"}, "/trigger/mode": {"x": "s"}}, []) == []
    found = check(c, {"/trigger/person": {"name": "n", "age": 1}, "/trigger/mode": {"mode": 1, "x": "s"}}, [])
    assert [(p.code, p.pointer) for p in found] == [(SEED_INVALID, "/trigger/mode"), (SEED_INVALID, "/trigger/person")]


def test_a_null_the_uses_take_is_taken_inside_a_choice() -> None:
    either = {
        "anyOf": [
            {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False},
            {"type": "object", "properties": {"name": {"type": "integer"}}, "additionalProperties": False},
        ]
    }
    fields = {"e": cel("trigger.either"), "n": ref("trigger.either.name", default=None)}
    c = of(with_input(either=either).node("t", TRANSFORM, {"fields": fields}), "t")
    assert check(c, {"/trigger/either": {"name": None}}, []) == []
    assert [p.code for p in check(c, {"/trigger/either": {"name": [1]}}, [])] == [SEED_INVALID]


def test_a_read_through_an_index_keeps_its_allowances_in_the_whole_list() -> None:
    """`aps[0].mac` with a default takes null at `/0/mac`; an element no use reads keeps its schema's type."""
    c = of(graph().node("t", TRANSFORM, {"fields": {"m": ref("trigger.aps[0].mac", default="fallback")}}), "t")
    assert check(c, {"/trigger/aps": [{"mac": None}]}, []) == []
    assert [p.code for p in check(c, {"/trigger/aps": [{"mac": "a"}, {"mac": None}]}, [])] == [SEED_INVALID]


def test_a_filters_predicate_reads_bind_each_element_of_the_list_it_filters() -> None:
    """`item` and `index` are never seeds, but what the predicate reads of each element is the filtered list's to
    hold: strictly read, every element has it; guarded, none needs it. A list computed from a value can't be traced
    so: what it's computed from keeps its schema's `required`."""
    strict = of(graph().node("f", FILTER, {"items": ref("trigger.aps"), "predicate": cel("item.mac == 'm'")}), "f")
    assert check(strict, {"/trigger/aps": [{"mac": "m"}]}, []) == [] and check(strict, {"/trigger/aps": []}, []) == []
    [problem] = check(strict, {"/trigger/aps": [{"mac": "m"}, {}]}, [])
    assert (problem.code, problem.pointer, problem.message) == (
        SEED_INVALID,
        "/trigger/aps",
        "This value must hold /*/mac.",
    )
    guarded = cel("has(item.mac) && item.mac == 'm'")
    g = of(graph().node("f", FILTER, {"items": ref("trigger.aps"), "predicate": guarded}), "f")
    assert check(g, {"/trigger/aps": [{}]}, []) == []
    computed = of(
        graph().node("f", FILTER, {"items": cel("trigger.aps + []"), "predicate": cel("item.mac == 'm'")}), "f"
    )
    assert [p.code for p in check(computed, {"/trigger/aps": [{}]}, [])] == [SEED_INVALID]


def test_a_guarded_read_inside_a_value_holds_only_where_its_guard_is_there() -> None:
    """Merged into a value read whole, `has(boss.profile) ? boss.profile.name : …` keeps its condition: no `profile`
    is fine; a `profile` given must hold `name`."""
    profile = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"],
               "additionalProperties": False}  # fmt: skip
    boss = {"type": "object", "properties": {"profile": profile}, "additionalProperties": False}
    fields = {"o": cel("trigger.boss"), "n": cel("has(trigger.boss.profile) ? trigger.boss.profile.name : 'absent'")}
    c = of(with_input(boss=boss).node("t", TRANSFORM, {"fields": fields}), "t")
    assert table(c)["/trigger/boss"][4] == ("/profile/name where /profile is there and isn't null",)
    assert (
        check(c, {"/trigger/boss": {}}, []) == [] and check(c, {"/trigger/boss": {"profile": {"name": "x"}}}, []) == []
    )
    [problem] = check(c, {"/trigger/boss": {"profile": {}}}, [])
    assert problem.message == "This value must hold /profile/name where /profile is there and isn't null."


def test_a_read_a_non_null_test_guards_holds_only_where_that_isnt_null() -> None:
    """`profile != null ? profile.name : …` keeps its condition, merged or mapped: a null `profile` is fine, an object
    must hold `name`. The comparison still reads `profile` itself, so it must be there."""
    profile = {"type": ["object", "null"], "properties": {"name": {"type": "string"}}, "required": ["name"],
               "additionalProperties": False}  # fmt: skip
    boss = {
        "type": "object",
        "properties": {"profile": profile},
        "required": ["profile"],
        "additionalProperties": False,
    }
    guarded = "trigger.boss.profile != null ? trigger.boss.profile.name : 'absent'"
    c = of(with_input(boss=boss).node("t", TRANSFORM, {"fields": {"o": cel("trigger.boss"), "n": cel(guarded)}}), "t")
    for ok in ({"profile": None}, {"profile": {"name": "x"}}):
        assert check(c, {"/trigger/boss": ok}, []) == [], ok
    for bad in ({"profile": {}}, {}):
        assert [p.code for p in check(c, {"/trigger/boss": bad}, [])] == [SEED_INVALID], bad
    bosses = {"type": "array", "items": boss}
    predicate = cel("item.profile != null ? item.profile.name == 'x' : false")
    f = of(with_input(bosses=bosses).node("f", FILTER, {"items": ref("trigger.bosses"), "predicate": predicate}), "f")
    assert check(f, {"/trigger/bosses": [{"profile": None}, {"profile": {"name": "x"}}]}, []) == []
    assert [p.code for p in check(f, {"/trigger/bosses": [{"profile": {}}]}, [])] == [SEED_INVALID]


def test_a_filters_reads_through_its_items_keep_their_conditions() -> None:
    """`items` through an index, with a default: the list may be missing or empty (the default, or no element); the
    elements there hold what the predicate reads. A list its items default may be null too."""
    aps = {"type": "array", "items": {"type": "object", "properties": {"mac": {"type": "string"}}, "required": ["mac"],
                                      "additionalProperties": False}}  # fmt: skip
    groups = {"type": "array", "items": {"type": "object", "properties": {"aps": aps}, "additionalProperties": False}}
    items = ref("trigger.groups[0].aps", default=[])
    c = of(with_input(groups=groups).node("f", FILTER, {"items": items, "predicate": cel("item.mac == 'm'")}), "f")
    for ok in ([], [{}], [{"aps": []}], [{"aps": [{"mac": "m"}]}]):
        assert check(c, {"/trigger/groups": ok}, []) == [], ok
    [problem] = check(c, {"/trigger/groups": [{"aps": [{}]}]}, [])
    assert problem.message == "This value must hold /0/aps/*/mac where /0/aps is there and isn't null."
    d = of(
        graph().node("f", FILTER, {"items": ref("trigger.aps", default=[]), "predicate": cel("item.mac == 'm'")}), "f"
    )
    assert check(d, {"/trigger/aps": None}, []) == [] and check(d, {}, ["/trigger/aps"]) == []


def test_a_computed_list_keeps_required_only_for_a_strict_read() -> None:
    computed = cel("trigger.aps + []")
    guarded = of(graph().node("f", FILTER, {"items": computed, "predicate": cel("has(item.mac) && item.mac == 'm'")}),
                 "f")  # fmt: skip
    assert check(guarded, {"/trigger/aps": [{}]}, []) == []
    strict = of(graph().node("f", FILTER, {"items": computed, "predicate": cel("item.mac == 'm'")}), "f")
    assert [p.code for p in check(strict, {"/trigger/aps": [{}]}, [])] == [SEED_INVALID]


def test_a_null_a_default_takes_stands_for_a_value_that_picks_its_own_branch() -> None:
    """`oneOf` as `anyOf` once the uses' allowances are excused: a real value there would match one branch."""
    profile = {
        "oneOf": [
            {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False},
            {"type": "object", "properties": {"name": {"type": "integer"}}, "additionalProperties": False},
        ]
    }
    owner = {
        "type": "object",
        "properties": {"profile": profile},
        "required": ["profile"],
        "additionalProperties": False,
    }
    fields = {"o": cel("trigger.boss"), "n": ref("trigger.boss.profile.name", default=None)}
    c = of(with_input(boss=owner).node("t", TRANSFORM, {"fields": fields}), "t")
    assert check(c, {"/trigger/boss": {"profile": {"name": None}}}, []) == []
    assert [p.code for p in check(c, {"/trigger/boss": {"profile": {"name": [1]}}}, [])] == [SEED_INVALID]


def test_a_filters_per_element_names_are_never_seeds() -> None:
    g = graph().node("f", FILTER, {"items": ref("trigger.aps"), "predicate": cel("item.mac == trigger.site")})
    assert set(table(of(g, "f"))) == {"/trigger/aps", "/trigger/site"}


def test_a_step_that_cant_run_alone_has_no_contract() -> None:
    g = graph().node("l", LOOP, {"items": ref("trigger.aps")}).node("x", ECHO, {"value": 1}).edge("l", "x", "body")
    assert of(g, "l").refused == NOT_ALONE


def test_seeds_are_checked_against_the_contract() -> None:
    fields = {"note": ref("trigger.note", default=None), "site": ref("trigger.site")}
    g = graph().node("t", TRANSFORM, {"fields": fields})
    c = of(g, "t")
    assert check(c, {"/trigger/site": "HQ", "/trigger/note": None}, []) == []
    assert check(c, {"/trigger/site": "HQ"}, ["/trigger/note"]) == []  # optional: absent
    found = check(c, {"/trigger/site": None, "/run/now": "x"}, ["/trigger/note", "/trigger/note"])
    assert [(p.code, p.pointer) for p in found] == [(SEED_UNKNOWN, "/run/now"), (SEED_INVALID, "/trigger/site")]
    assert [p.code for p in check(c, {"/trigger/note": None}, ["/trigger/site"])] == [SEED_MISSING]
    assert [p.code for p in check(c, {"/trigger/site": 5, "/trigger/note": None}, [])] == [SEED_INVALID]


def test_a_whole_number_is_a_number_and_null_needs_a_nullable_path() -> None:
    g = graph()
    g.settings["input_schema"]["properties"]["ratio"] = {"type": "number"}
    g.settings["input_schema"]["required"].append("ratio")
    g.node("t", TRANSFORM, {"fields": {"r": ref("trigger.ratio")}})
    c = of(g, "t")
    assert check(c, {"/trigger/ratio": 2}, []) == [] and check(c, {"/trigger/ratio": 2.5}, []) == []
    assert [p.code for p in check(c, {"/trigger/ratio": "2"}, [])] == [SEED_INVALID]
