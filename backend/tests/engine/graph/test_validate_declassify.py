# SPDX-License-Identifier: Apache-2.0
"""Declassification (engine 2b spec §4.3): only a `flow.if` condition, a `flow.switch` case's `when`, a loop's
`items` and a filter's `items` or `predicate` may turn tainted input into a plain decision, and each such site must be
listed in `graph.settings.declassify`. Publish refuses an unlisted tainted decision and a stale entry. A loop over
the rows of a version's CSV, `trigger.rows`, whose length is already public (`trigger.row_count`), needs no entry."""

from typing import Any

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
