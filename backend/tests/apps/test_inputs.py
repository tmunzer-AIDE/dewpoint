# SPDX-License-Identifier: Apache-2.0
"""A run's input refused at admission, or a sub-flow's at its crossing (engine 2b spec §3.5): each place it breaks and
the rule, never what's there. A place the data supplied, a map's key, shows as `*`: the key can be a secret."""

import json
import threading
from typing import Any

import pytest

from dewpoint.apps.inputs import TOO_DEEP, TOO_DEEP_TO_CHECK, InputRefusedError, checked, nests_too_deep, reasons
from dewpoint.core.ingress.parsing import MalformedError, parse
from dewpoint.engine.graph.model import MAX_DEPTH

KEY = "".join(["canary", "-map-", "key"])  # a key the data supplied
CREDS = {
    "type": "object",
    "properties": {"creds": {"type": "object", "x-sensitive": True, "additionalProperties": {"type": "integer"}}},
    "required": ["creds"],
    "additionalProperties": False,
}
ROWS = {"type": "object", "properties": {"rows": {"type": "array", "items": {"type": "integer"}}}, "required": ["rows"]}
WHY = "The run's input doesn't match the workflow's input schema at {}: it breaks `{}`."


def test_a_refusal_names_a_map_key_as_a_star_never_the_key() -> None:
    assert reasons(CREDS, {"creds": {KEY: "not an integer"}}) == [WHY.format("creds.*", "type")]


def test_a_refusal_names_declared_properties_positions_and_the_root() -> None:
    assert reasons(ROWS, {"rows": [1, "x"]}) == [WHY.format("rows.1", "type")]
    assert reasons(ROWS, []) == [WHY.format("its root", "type")]
    assert reasons(CREDS, {"creds": {}, KEY: 1}) == [WHY.format("its root", "additionalProperties")]


def test_a_rule_broken_at_one_place_is_told_once() -> None:
    """jsonschema reports `required` once per missing property, `dependentRequired` once per missing dependency and a
    `propertyNames` rule once per name it refuses, and map keys breaking one rule show as one `*`: each place and rule
    is told once, so repeats never take the place of another reason."""
    schema = {
        "type": "object",
        "properties": {
            "rows": {"type": "array"},
            "creds": {"type": "object", "additionalProperties": {"type": "integer"}},
        },
        "required": ["a", "b"],
        "dependentRequired": {"rows": ["x", "y"]},
        "propertyNames": {"maxLength": 5},
    }
    value = {"rows": 1, "creds": {KEY: "x", f"{KEY}-2": "y"}, KEY: 0, f"{KEY}-2": 0}  # 9 errors, 5 places and rules
    assert reasons(schema, value) == [
        WHY.format("its root", "dependentRequired"),
        WHY.format("its root", "maxLength"),
        WHY.format("its root", "required"),
        WHY.format("creds.*", "type"),
        WHY.format("rows", "type"),
    ]


# Issue #88's schema: an object whose `n` is one of itself, without end.
RECURSIVE = {"type": "object", "properties": {"n": {"$ref": "#/$defs/n"}},
             "$defs": {"n": {"type": "object", "properties": {"n": {"$ref": "#/$defs/n"}}}}}  # fmt: skip


def objects(levels: int) -> dict[str, Any]:
    """`levels` objects, each the `n` of the one before: the root the first level."""
    value: dict[str, Any] = {}
    for _ in range(levels - 1):
        value = {"n": value}
    return value


def arrays(levels: int) -> Any:
    value: Any = []
    for _ in range(levels - 1):
        value = [value]
    return value


def test_the_limit_is_the_engines_for_a_document() -> None:
    assert MAX_DEPTH == 64


@pytest.mark.parametrize("build", [objects, arrays])
def test_an_input_nests_at_most_64_levels(build: Any) -> None:
    assert not nests_too_deep(build(63)) and not nests_too_deep(build(64))
    assert nests_too_deep(build(65))
    assert not nests_too_deep({"n": build(63)}) and nests_too_deep({"n": build(64)})


def test_scalars_are_no_level() -> None:
    """Objects and arrays nest; a string, a number, true, false or null at the 65th place doesn't add a level."""
    value: Any = "leaf"
    for _ in range(64):
        value = {"n": value}
    assert not nests_too_deep(value)


@pytest.mark.parametrize("build", [objects, arrays])
@pytest.mark.parametrize("levels", [63, 64, 65])
def test_the_count_is_the_webhook_parsers(build: Any, levels: int) -> None:
    """An event the ingress parser accepts is an input admission accepts: the same levels, counted the same way."""
    value = build(levels)
    try:
        parse(json.dumps(value).encode())
        parsed = True
    except MalformedError:
        parsed = False
    assert parsed is not nests_too_deep(value)


def test_any_depth_is_counted_without_error() -> None:
    assert nests_too_deep(objects(100_000))


def test_an_input_past_the_limit_is_refused_before_its_schema_is_read() -> None:
    """Under issue #88's recursive schema, 300 levels raised RecursionError: refused with the fixed reason instead."""
    with pytest.raises(InputRefusedError) as raised:
        checked(RECURSIVE, objects(300))
    assert raised.value.reasons == [TOO_DEEP] and raised.value.reason == "input_invalid"
    with pytest.raises(InputRefusedError) as raised:
        checked({"type": "object"}, objects(65))  # a permissive schema: refused all the same
    assert raised.value.reasons == [TOO_DEEP]
    assert TOO_DEEP == "The run's input nests deeper than 64 levels."


def test_reasons_never_raises_recursion_error() -> None:
    """A schema that spends many frames a level could still reach the recursion limit within 64 levels: told, not
    raised (defence in depth: every entry checks the depth first)."""
    assert reasons(RECURSIVE, objects(300)) == [TOO_DEEP_TO_CHECK]
    assert TOO_DEEP_TO_CHECK == "The run's input is nested too deeply to check against the workflow's input schema."


def test_the_recursive_schema_validates_at_the_limit_in_the_main_thread_and_a_worker_thread() -> None:
    assert reasons(RECURSIVE, objects(MAX_DEPTH)) == []
    found: list[Any] = []
    worker = threading.Thread(target=lambda: found.append(reasons(RECURSIVE, objects(MAX_DEPTH))))
    worker.start()
    worker.join()
    assert found == [[]]


def test_at_a_crossing_a_handle_is_a_leaf() -> None:
    """The review's L1: a value 64 levels deep whose deepest leaf a parent's step claimed holds the handle object at
    level 65; resolved, it's 64. At the crossing a handle counts as the leaf it stands for (the bounded resolver counts
    what it expands to); anywhere else an input holds no handle (the marker is refused), and it counts as an object."""
    from dewpoint.engine.handles import ClaimRef

    value: Any = ClaimRef("00000000-0000-0000-0000-000000000007").to_json()
    for _ in range(64):
        value = {"n": value}
    assert nests_too_deep(value) and not nests_too_deep(value, handles=True)
    assert nests_too_deep({"n": value}, handles=True)  # 65 levels without the handle
