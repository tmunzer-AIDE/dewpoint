# SPDX-License-Identifier: Apache-2.0
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dewpoint.engine.graph.values import (
    CelValue,
    LiteralValue,
    RefSyntaxError,
    RefValue,
    TemplateRef,
    TemplateValue,
    ValueSyntaxError,
    iter_values,
    parse_ref,
    pointer_str,
    strip_values,
)


@pytest.mark.parametrize(
    ("text", "root", "name", "section", "rest"),
    [
        ("trigger.site.devices[0].mac", "trigger", None, None, ("site", "devices", 0, "mac")),
        ("steps.get_site.output.name", "steps", "get_site", "output", ("name",)),
        ("steps.get_site.error.code", "steps", "get_site", "error", ("code",)),
        ("vars.count", "vars", "count", None, ()),
        ("loop.item.name", "loop", None, "item", ("name",)),
        ("loop.index", "loop", None, "index", ()),
        ("loops.outer.item", "loops", "outer", "item", ()),
        ("run.now", "run", None, "now", ()),
    ],
)
def test_parse_ref(text: str, root: str, name: str | None, section: str | None, rest: tuple[Any, ...]) -> None:
    r = parse_ref(text)
    assert (r.root, r.name, r.section, r.rest, r.text) == (root, name, section, rest, text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "steps",
        "steps.a",
        "steps.a.oops",
        "steps.a.error.detail",
        "loop.index.x",
        "run.clock",
        "env.HOME",
        "trigger..x",
        "trigger.x[01]",
        "trigger.x[",
        ".trigger",
    ],
)
def test_bad_refs(text: str) -> None:
    with pytest.raises(RefSyntaxError):
        parse_ref(text)


def test_iter_values_finds_nested_envelopes_in_order() -> None:
    config = {
        "b": {"$value": {"kind": "ref", "path": "vars.x", "default": 0}},
        "a": [
            1,
            {"$value": {"kind": "cel", "expr": "1 + 1"}},
            {"deep": {"$value": {"kind": "literal", "value": {"$value": 1}}}},
        ],
        "t": {"$value": {"kind": "template", "parts": [{"text": "hi "}, {"ref": "vars.name", "default": "you"}]}},
    }
    found = list(iter_values(config))
    assert [pointer_str(p) for p, _ in found] == ["/a/1", "/a/2/deep", "/b", "/t"]
    cel = found[0][1]
    assert isinstance(cel, CelValue) and cel.expr == "1 + 1"
    assert found[1][1] == LiteralValue({"$value": 1})
    ref = found[2][1]
    assert isinstance(ref, RefValue) and ref.has_default and ref.default == 0
    tpl = found[3][1]
    assert isinstance(tpl, TemplateValue) and tpl.parts[0] == "hi "
    assert isinstance(tpl.parts[1], TemplateRef) and tpl.parts[1].default == "you"


@pytest.mark.parametrize(
    "body",
    [
        {"$value": {"kind": "python", "code": "x"}},
        {"$value": {"kind": "ref", "path": "vars.x", "extra": 1}},
        {"$value": {"kind": "ref", "path": "nope.x"}},
        {"$value": {"kind": "template", "parts": []}},
        {"$value": {"kind": "template", "parts": [{"ref": "vars.x", "default": 3}]}},
        {"$value": {"kind": "cel", "expr": "x" * 16_385}},
        {"$value": {"kind": "literal"}},
        {"$value": {"kind": "ref", "path": "vars.x"}, "other": 1},
    ],
)
def test_envelope_errors_are_reported_in_place(body: dict[str, Any]) -> None:
    [(pointer, value)] = list(iter_values({"f": body}))
    assert pointer == ("f",) and isinstance(value, ValueSyntaxError)


def test_strip_values_replaces_envelopes_with_null() -> None:
    stripped, pointers = strip_values({"a": 1, "b": [{"$value": {"kind": "cel", "expr": "x"}}, 2]})
    assert stripped == {"a": 1, "b": [None, 2]} and pointers == [("b", 0)]


def test_pointer_escaping() -> None:
    assert pointer_str(("a/b", "c~d", 0)) == "/a~1b/c~0d/0"


@pytest.mark.parametrize("kind", [[], {}, 3, None, True])
def test_non_text_kinds_are_syntax_errors(kind: Any) -> None:
    [(_, value)] = list(iter_values({"f": {"$value": {"kind": kind}}}))
    assert isinstance(value, ValueSyntaxError)


KEYS = st.sampled_from(["$value", "kind", "path", "parts", "expr", "value", "default", "text", "ref"]) | st.text(
    max_size=6
)
JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(KEYS, inner, max_size=4),
    max_leaves=20,
)


@settings(max_examples=300, deadline=None)
@given(JSON)
def test_arbitrary_envelopes_are_reported_never_raised(body: Any) -> None:
    for _, value in iter_values({"f": {"$value": body}, "g": body}):
        assert value is not None
