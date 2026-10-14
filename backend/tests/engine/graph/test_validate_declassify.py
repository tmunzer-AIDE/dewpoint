# SPDX-License-Identifier: Apache-2.0
"""Declassification (engine 2b spec §4.3): only a `flow.if` condition, a `flow.switch` case's `when`, a loop's
`items` and a filter's `items` or `predicate` may turn tainted input into a plain decision, and each such site must be
listed in `graph.settings.declassify`. Publish refuses an unlisted tainted decision and a stale entry. A loop over
the rows of a version's CSV, `trigger.rows`, whose length is already public (`trigger.row_count`), needs no entry."""

from typing import Any

import pytest

from dewpoint.engine.graph.validate import ValidationContext, ValidationResult, validate
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G, cel, nid, ref
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
ECHO, IF, SWITCH, LOOP, FILTER = "testkit.echo@1", "flow.if@1", "flow.switch@1", "flow.loop@1", "flow.filter@1"
SECRET = {"type": "string", "x-sensitive": True}
ROW = {"type": "object", "properties": {"id": {"type": "integer"}, "card": SECRET}, "required": ["id", "card"],
       "additionalProperties": False}  # fmt: skip
CARD = {"header": "Card", "name": "card", "type": "string", "required": True, "sensitive": True}
CSV = {"columns": [{"header": "ID", "name": "id", "type": "integer", "required": True}, CARD]}
INPUT = {
    "type": "object",
    "properties": {"token": SECRET, "n": {"type": "integer"}, "list": {"type": "array", "items": ROW}},
    "required": ["token", "n", "list"],
    "additionalProperties": False,
}  # fmt: skip


def check(g: G, *declassify: tuple[str, str]) -> ValidationResult:
    g.settings = {"input_schema": INPUT, "csv": CSV,
                  "declassify": [{"node": str(nid(k)), "field": f} for k, f in declassify]}  # fmt: skip
    return validate(g.build(), ValidationContext(catalog=CAT))


def codes(result: ValidationResult) -> list[tuple[str, str | None]]:
    return [(d.code, d.field) for d in result.diagnostics]


def branch(condition: Any) -> G:
    return (
        G()
        .node("c", IF, {"condition": condition})
        .node("a", ECHO)
        .node("b", ECHO)
        .edge("c", "a", "true")
        .edge("c", "b", "false")
    )


def test_a_tainted_condition_must_be_listed() -> None:
    tainted = branch(cel("size(trigger.token) > 8"))
    assert ("taint.undeclassified", "/condition") in codes(check(tainted))
    listed = check(branch(cel("size(trigger.token) > 8")), ("c", "/condition"))
    assert listed.ok and listed.declassified == ((str(nid("c")), "/condition", "the branch taken"),)


def test_a_plain_decision_needs_no_entry_and_a_stale_one_is_refused() -> None:
    assert check(branch(cel("trigger.n > 3"))).ok
    assert ("taint.stale_declassify", "/settings/declassify/0") in codes(
        check(branch(cel("trigger.n > 3")), ("c", "/condition"))
    )
    assert ("taint.stale_declassify", "/settings/declassify/0") in codes(check(branch(True), ("a", "/value")))


def test_a_switch_case_is_listed_by_its_own_when() -> None:
    cases = [{"port": "small", "when": cel("trigger.n < 3")}, {"port": "long", "when": cel("size(trigger.token) > 8")}]
    g = G().node("s", SWITCH, {"cases": cases}).node("a", ECHO).node("b", ECHO).node("d", ECHO)
    g.edge("s", "a", "small").edge("s", "b", "long").edge("s", "d", "default")
    assert codes(check(g)) == [("taint.undeclassified", "/cases/1/when")]


def entries(g: G, *listed: dict[str, Any]) -> ValidationResult:
    """The graph checked with these entries as written (a node's id in any spelling)."""
    g.settings = {"input_schema": INPUT, "csv": CSV, "declassify": list(listed)}
    return validate(g.build(), ValidationContext(catalog=CAT))


def test_a_repeated_entry_is_refused_and_the_first_copy_still_counts() -> None:
    """#78: a repeat would keep the decision declassified after a person removes the copy they see."""
    result = check(branch(cel("size(trigger.token) > 8")), ("c", "/condition"), ("c", "/condition"))
    assert codes(result) == [("taint.repeated_declassify", "/settings/declassify/1")]
    assert result.declassified == ((str(nid("c")), "/condition", "the branch taken"),)


def test_a_repeat_is_found_whatever_the_ids_spelling() -> None:
    node = str(nid("c"))
    result = entries(branch(cel("size(trigger.token) > 8")), {"node": node, "field": "/condition"},
                     {"node": "{" + node.upper() + "}", "field": "/condition"})  # fmt: skip
    assert codes(result) == [("taint.repeated_declassify", "/settings/declassify/1")]


def test_a_repeat_of_a_stale_entry_is_reported_as_a_repeat_and_the_first_copy_as_stale() -> None:
    result = check(branch(cel("trigger.n > 3")), ("c", "/condition"), ("c", "/condition"))
    assert codes(result) == [
        ("taint.stale_declassify", "/settings/declassify/0"),
        ("taint.repeated_declassify", "/settings/declassify/1"),
    ]


def test_distinct_entries_up_to_the_cap_are_never_repeats() -> None:
    listed = [("c", f"/x{i}") for i in range(200)]
    found = {code for code, _ in codes(check(branch(cel("trigger.n > 3")), *listed))}
    assert found == {"taint.stale_declassify"}


CASES = [{"port": "small", "when": cel("trigger.n < 3")}, {"port": "long", "when": cel("size(trigger.token) > 8")}]


def switch(cases: list[dict[str, Any]]) -> G:
    g = G().node("s", SWITCH, {"cases": cases}).node("a", ECHO).node("b", ECHO).node("d", ECHO)
    return g.edge("s", "a", "small").edge("s", "b", "long").edge("s", "d", "default")


def test_a_switch_cases_entry_names_its_port_and_counts_while_its_case_is_there() -> None:
    node = str(nid("s"))
    result = entries(switch(CASES), {"node": node, "field": "/cases/1/when", "port": "long"})
    assert result.ok and result.declassified == ((node, "/cases/1/when", "the port taken"),)


@pytest.mark.parametrize(
    ("cases", "entry", "undeclassified"),
    [
        (CASES, {"field": "/cases/1/when"}, "/cases/1/when"),  # no port: written before #78
        (CASES, {"field": "/cases/1/when", "port": "small"}, "/cases/1/when"),  # another case's
        (CASES[::-1], {"field": "/cases/1/when", "port": "long"}, "/cases/0/when"),  # reordered, the entry untouched
    ],
    ids=["no-port", "another-port", "reordered"],
)
def test_a_switch_cases_entry_that_doesnt_name_the_case_at_its_place_declassifies_nothing(
    cases: list[dict[str, Any]], entry: dict[str, str], undeclassified: str
) -> None:
    """#78: a case's decision is declassified by its port, so a reorder outside the editor (the API, an import) is
    reported, never followed: the entry would otherwise declassify another case's decision."""
    result = entries(switch(cases), {"node": str(nid("s")), **entry})
    assert codes(result) == [
        ("taint.undeclassified", undeclassified),
        ("taint.case_declassify", "/settings/declassify/0"),
    ]
    assert result.declassified == ()


def test_a_port_on_an_entry_that_isnt_a_switch_cases_is_refused() -> None:
    result = entries(
        branch(cel("size(trigger.token) > 8")), {"node": str(nid("c")), "field": "/condition", "port": "true"}
    )
    assert codes(result) == [
        ("taint.undeclassified", "/condition"),
        ("taint.case_declassify", "/settings/declassify/0"),
    ]


def test_a_repeat_naming_the_case_never_counts_for_a_first_copy_that_doesnt() -> None:
    """The review of the build: the first copy names another case, the repeat names the right one; only a first copy
    may count, and this one doesn't, so the case's decision stays undeclassified."""
    node = str(nid("s"))
    result = entries(switch(CASES[::-1]), {"node": node, "field": "/cases/0/when", "port": "small"},
                     {"node": node, "field": "/cases/0/when", "port": "long"})  # fmt: skip
    assert codes(result) == [
        ("taint.undeclassified", "/cases/0/when"),
        ("taint.case_declassify", "/settings/declassify/0"),
        ("taint.repeated_declassify", "/settings/declassify/1"),
    ]


def test_a_case_without_a_literal_port_counts_no_entry() -> None:
    """The review of the build: a case whose port is missing or computed (refused as the step's structure) gives an
    entry nothing to match, so no entry counts for it, written with a port or without."""
    cases = [
        {"when": cel("size(trigger.token) > 8")},
        {"port": {"$value": {"kind": "cel", "expr": "'x'"}}, "when": True},
    ]
    g = G().node("s", SWITCH, {"cases": cases}).node("d", ECHO).edge("s", "d", "default")
    result = entries(g, {"node": str(nid("s")), "field": "/cases/0/when"})
    assert ("taint.case_declassify", "/settings/declassify/0") in codes(result)
    assert result.declassified == ()


def test_a_switch_whose_cases_arent_objects_is_checked_without_failing() -> None:
    g = G().node("s", SWITCH, {"cases": [1, "a", None, CASES[1]]}).node("d", ECHO).edge("s", "d", "default")
    result = entries(g, {"node": str(nid("s")), "field": "/cases/3/when", "port": "long"})
    assert not result.ok  # the step's structure is refused, and the case that is one is still named by its port
    assert result.declassified == ((str(nid("s")), "/cases/3/when", "the port taken"),)


def test_an_entry_for_a_decision_that_isnt_there_is_stale_whatever_port_it_names() -> None:
    """The review of the build: a deleted step's entry, or one past the end of the cases, isn't a decision at all."""
    gone = entries(switch(CASES), {"node": str(nid("gone")), "field": "/cases/0/when", "port": "small"})
    past = entries(switch(CASES), {"node": str(nid("s")), "field": "/cases/5/when", "port": "small"})
    for result in (gone, past):
        assert ("taint.stale_declassify", "/settings/declassify/0") in codes(result)
        assert ("taint.case_declassify", "/settings/declassify/0") not in codes(result)


def test_a_loop_over_tainted_items_must_be_listed_except_over_trigger_rows() -> None:
    def loop(items: Any) -> G:
        return G().node("l", LOOP, {"items": items}).node("x", ECHO, {"value": ref("item.id")}).edge("l", "x", "body")

    assert ("taint.undeclassified", "/items") in codes(check(loop(ref("trigger.list"))))
    assert check(loop(ref("trigger.list")), ("l", "/items")).ok
    assert check(loop(ref("trigger.rows"))).ok  # its length is public: no entry needed


def test_without_a_csv_a_loop_over_trigger_rows_needs_its_entry() -> None:
    """#31: only a version declaring a CSV has a public `row_count`, so only its loop over `trigger.rows` skips the
    entry (§4.3). Elsewhere `trigger.rows` is whatever the caller sent: here undeclared, so sensitive."""
    rows = ref("trigger.rows", default=[])  # undeclared, so optional: the default makes it a direct reference still
    g = G().node("l", LOOP, {"items": rows}).node("x", ECHO, {"value": 1}).edge("l", "x", "body")
    g.settings = {"input_schema": {"type": "object"}}
    assert codes(validate(g.build(), ValidationContext(catalog=CAT))) == [("taint.undeclassified", "/items")]
    g.settings["declassify"] = [{"node": str(nid("l")), "field": "/items"}]
    assert validate(g.build(), ValidationContext(catalog=CAT)).ok


def test_a_filter_lists_each_tainted_field() -> None:
    g = G().node("f", FILTER, {"items": [1, 2, 3], "predicate": cel("size(trigger.token) > item")})
    assert codes(check(g)) == [("taint.undeclassified", "/predicate")]
    assert check(G().node("f", FILTER, {"items": [1, 2], "predicate": cel("size(trigger.token) > item")}),
                 ("f", "/predicate")).ok  # fmt: skip
