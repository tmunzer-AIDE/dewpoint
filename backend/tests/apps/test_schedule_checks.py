# SPDX-License-Identifier: Apache-2.0
"""Whether a stored schedule input would fit a draft's input, by its shape alone (4c-3a ruling 7). The draft's input is
checked as written, by JSON Schema's own validator extended to evaluate only structure: the keywords that test a
value's content hold for every value, `oneOf` is evaluated as `anyOf`, and the structure a shape can't keep (`not`,
`if`, …) holds and is named. So the check accepts every value the draft does, nested fields, references and `allOf`
included. Never a value's content: a draft's `maximum` or `maxLength` against a stored value would let whoever
validates learn a sensitive value a bit at a time."""

import itertools
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError

from dewpoint.apps import schedule_checks
from dewpoint.apps.schedule_checks import (
    CSV,
    TOO_DEEP_STORED,
    Breaks,
    Checked,
    Exhausted,
    Shape,
    checked_all,
    shape,
    too_deep_schedules,
    warnings,
)

SECRET = "t0ken-value-1"
STORED = {"token": SECRET, "site": "a", "floor": 2, "address": {"city": "Paris"}, "tags": ["a", "b"]}


def schema(properties: dict[str, Any], **rest: Any) -> dict[str, Any]:
    return {"type": "object", "properties": properties} | rest


@pytest.mark.parametrize(
    ("input_schema", "reasons"),
    [
        (schema({"site": {"type": "string"}, "area": {"type": "string"}}, required=["site", "area"]),
         ["`area` is required now."]),
        (schema({"address": {"type": "object", "properties": {"zip": {"type": "string"}}, "required": ["zip"]}}),
         ["`address.zip` is required now."]),
        (schema({"site": {"type": "integer"}, "floor": {"type": "string"}}),
         ["`floor` must be text now.", "`site` must be a whole number now."]),
        (schema({"site": {"type": ["integer", "null"]}}), ["`site` must be a whole number or null now."]),
        ({"type": "object", "properties": {"floor": {"$ref": "#/$defs/label"}}, "$defs": {"label": {"type": "string"}}},
         ["`floor` must be text now."]),
        ({"type": "object", "allOf": [{"required": ["area"]}, {"properties": {"site": {"type": "boolean"}}}]},
         ["`area` is required now.", "`site` must be yes or no now."]),
        (schema({"tags": {"type": "array", "items": {"type": "integer"}}}),
         ["`tags.0` must be a whole number now.", "`tags.1` must be a whole number now."]),
        (schema({"floor": {"anyOf": [{"type": "string"}, {"type": "boolean"}]}}),
         ["`floor` fits none of the shapes this input allows."]),
        (schema({"token": {"type": "string"}}, additionalProperties=False),
         ["It has a field this input no longer allows."]),
        (schema({"address": {"type": "object", "properties": {}, "additionalProperties": False}}),
         ["`address` has a field this input no longer allows."]),
        (schema({"floor": {"type": "integer"}}, dependentRequired={"site": ["area"]}),
         ["`area` is required now, beside `site`."]),
        (schema({"floor": {"type": "integer"}}, required=["floor"]), []),
        (schema({"floor": {"type": "number"}}), []),
        (schema({"token": {"type": "string", "x-sensitive": True, "maxLength": 3, "minLength": 99}}), []),
        (schema({"floor": {"type": "integer", "maximum": 1, "multipleOf": 7, "const": 5, "enum": [9]},
                 "site": {"type": "string", "format": "email", "minLength": 40}}, minProperties=99), []),
        ({"type": "object"}, []),
    ],
    ids=["required", "nested-required", "type", "type-list", "reference", "all-of", "items", "any-of",
         "no-longer-allowed", "nested-no-longer-allowed", "dependent-required", "fits", "number-takes-an-integer",
         "sensitive-length", "value-constraints", "open"],
)  # fmt: skip
def test_a_stored_input_is_checked_by_its_shape(input_schema: dict[str, Any], reasons: list[str]) -> None:
    found = shape(input_schema, takes_csv=False)
    assert found.check(STORED) == Checked(reasons, more=False) and found.partial == frozenset()


def test_an_integral_number_is_a_whole_number() -> None:
    """As JSON Schema says it, and admission's validator with it: `2.0` is an integer; `2.5` and `true` aren't."""
    whole = shape(schema({"floor": {"type": "integer"}}), takes_csv=False)
    assert [whole.check({"floor": v}).reasons for v in (2.0, 0.0, 2)] == [[], [], []]
    assert (
        whole.check({"floor": 2.5}).reasons
        == whole.check({"floor": True}).reasons
        == ["`floor` must be a whole number now."]
    )


def test_a_reason_never_holds_a_value_or_a_stored_name() -> None:
    """The reasons name the draft's own fields, never the stored input's: a field the draft no longer allows is
    counted, not named, and a key the data supplied shows as `*`."""
    stored = STORED | {"secret-name": {"x": 1}}
    found = shape(schema({"site": {"type": "integer"}}, additionalProperties={"required": ["y"]},
                         required=["site", "x"]), takes_csv=False).check(stored).reasons  # fmt: skip
    assert found == ["`*.y` is required now.", "`site` must be a whole number now.", "`x` is required now."]
    assert not any(word in r for r in found for word in (SECRET, "secret-name", "Paris", "token", "address"))


@pytest.mark.parametrize(
    ("input_schema", "partial"),
    [
        (schema({"kind": {"oneOf": [{"const": "a"}, {"const": "b"}]}}), {"oneOf"}),
        (schema({"site": {"type": "string"}}, **{"not": {"required": ["site"]}}), {"not"}),
        (schema({}, **{"if": {"required": ["a"]}, "then": {"required": ["b"]}}), {"if", "then"}),
        (schema({}, propertyNames={"maxLength": 2}, unevaluatedProperties=False), {"propertyNames",
                                                                                   "unevaluatedProperties"}),
        (schema({"tags": {"type": "array", "contains": {"const": "x"}}}), {"contains"}),
    ],
    ids=["one-of", "not", "if-then", "names-and-unevaluated", "contains"],
)  # fmt: skip
def test_structure_the_shape_cant_keep_is_named_and_never_refuses(input_schema: dict[str, Any],
                                                                    partial: set[str]) -> None:  # fmt: skip
    """What the shape can't keep is dropped (or, for `oneOf`, read as `anyOf`), so the check widens and never refuses
    what the draft accepts; and it's named, so validate can say the schedules were checked in part."""
    found = shape(input_schema, takes_csv=False)
    assert found.partial == frozenset(partial) and found.check(STORED | {"kind": "a"}) == Checked([], more=False)


def test_an_input_that_takes_a_csv_file_fits_no_schedule() -> None:
    """Its rows come from an upload only (engine 2b spec §8.1): a schedule can't give them, whatever its input."""
    assert shape({"type": "object"}, takes_csv=True).check(STORED) == Checked([CSV], more=False)


def test_a_stored_input_is_read_within_its_budgets() -> None:
    """The review of revision 2: a 400 KB input whose 20,000 items all broke the draft's new item type gave 20,000
    reasons. The check reads a stored input's errors lazily, stops at `MAX_ERRORS` read or `MAX_REASONS` distinct
    reasons kept, and says it stopped (`more`)."""
    found = shape(schema({"tags": {"type": "array", "items": {"type": "integer"}}}), takes_csv=False)
    checked = found.check({"tags": ["a"] * 20_000})
    assert checked.more is True and len(checked.reasons) == schedule_checks.MAX_REASONS
    assert checked.reasons[0] == "`tags.0` must be a whole number now."


def test_a_union_is_tried_branch_by_branch_up_to_a_first_error() -> None:
    """The review of revision 3: JSON Schema's own `anyOf` builds every error of every failing branch before it
    yields one (three branches over 20,000 items: 60,000 errors). The check's `anyOf` tries each branch up to its
    first error and keeps none of them: it never names them."""
    union = {"anyOf": [{"items": {"type": "integer"}}, {"items": {"type": "boolean"}}, {"items": {"type": "null"}}]}
    found = shape(schema({"tags": {"type": "array"} | union}), takes_csv=False)
    assert found.check({"tags": ["abcdefghijklmnopq"] * 20_000}) == Checked(
        ["`tags` fits none of the shapes this input allows."]
    )
    assert schedule_checks.MAX_STEPS - found.budget.left < 50


def test_every_step_of_the_check_spends_from_one_budget(monkeypatch) -> None:
    """Every keyword the check evaluates, at any depth, spends one step of the check's budget (`MAX_STEPS`, for all
    its inputs together); when it runs out, the check stops, and what's left is counted unchecked, never refused."""
    monkeypatch.setattr(schedule_checks, "MAX_STEPS", 1_000)
    typed = schema({"tags": {"type": "array", "items": {"type": "string"}}})
    with pytest.raises(Exhausted):
        shape(typed, takes_csv=False).check({"tags": ["a"] * 5_000})
    opened = [(uuid.uuid4(), json.dumps({"tags": ["a"] * 400}).encode()) for _ in range(5)]
    partial, refused, unchecked = checked_all(typed, False, opened)
    assert (partial, refused, unchecked) == (frozenset(), [], 3)  # 2 fit in 1,000 steps; the third ran out


DIALECT = "https://json-schema.org/draft/2020-12/schema"
BRANCHES = [{"items": {"type": kind}} for kind in ("integer", "boolean", "null")]


@pytest.mark.parametrize(
    "tags",
    [{"$schema": DIALECT, "type": "array", "anyOf": BRANCHES},
     {"type": "array", "anyOf": [{"$schema": DIALECT} | branch for branch in BRANCHES]}],
    ids=["on-the-union", "in-each-branch"],
)  # fmt: skip
def test_a_dialect_declared_inside_never_leaves_the_checks_validator(tags: dict[str, Any]) -> None:
    """The review of revision 4: jsonschema picks a subschema's validator by its own `$schema`, so a union under one
    naming 2020-12 ran on JSON Schema's own validator, unbudgeted (2 steps counted), its `anyOf` building 60,001
    errors over this input. The check's own dialect is removed wherever a schema stands: the union is still tried a
    branch at a time up to a first error, each step counted."""
    found = shape(schema({"tags": tags}, **{"$schema": DIALECT}), takes_csv=False)
    assert found.check({"tags": ["abcdefghijklmnopq"] * 20_000}) == Checked(
        ["`tags` fits none of the shapes this input allows."]
    )
    assert 5 < schedule_checks.MAX_STEPS - found.budget.left < 50 and found.partial == frozenset()


def test_a_dialect_declared_inside_still_spends_the_budget(monkeypatch) -> None:
    """The review of revision 4: a valid 20,000-item list beneath a nested `$schema` finished on 4 steps. It spends
    the check's steps as anywhere else, through a reference too, and runs out."""
    monkeypatch.setattr(schedule_checks, "MAX_STEPS", 4)
    nested = {"type": "object", "properties": {"tags": {"$ref": "#/$defs/tags"}},
              "$defs": {"tags": {"$schema": DIALECT, "type": "array", "items": {"type": "string"}}}}  # fmt: skip
    with pytest.raises(Exhausted):
        shape(nested, takes_csv=False).check({"tags": ["a"] * 20_000})


def test_another_dialect_isnt_checked_and_says_so() -> None:
    """A schema naming another dialect is read by that dialect's rules, which the check doesn't keep: it isn't checked
    (never a reason, no step spent), and `$schema` is named, for validate to say the check was partial."""
    found = shape(schema({"site": {"$schema": "http://json-schema.org/draft-07/schema#", "type": "integer"}}),
                  takes_csv=False)  # fmt: skip
    assert found.check(STORED) == Checked([]) and found.partial == frozenset({"$schema"})
    assert found.budget.left == schedule_checks.MAX_STEPS


def test_a_reference_resolves_wherever_its_schema_stands() -> None:
    """The draft's schema is kept as written but for the check's own `$schema`: a reference resolves as it does for the
    draft, its definition's structure checked, and a keyword the check doesn't evaluate there (a `not`) named."""
    kept = {"properties": {"inner": {"type": "string"}}, "not": {"type": "integer"}}
    referring = {"type": "object", "properties": {"site": {"$ref": "#/$defs/kept"}}, "$defs": {"kept": kept}}
    found = shape(referring, takes_csv=False)
    assert found.check({"site": {"inner": 1}}) == Checked(["`site.inner` must be text now."])
    assert found.partial == frozenset({"not"})


def test_a_key_its_pattern_allows_is_no_extra_field() -> None:
    """Keywords the check doesn't evaluate stay in the schema: `additionalProperties` still reads `patternProperties`,
    so a key a pattern allows is never reported as one the input no longer allows."""
    patterned = schema({}, patternProperties={"^t": {}}, additionalProperties=False)
    assert shape(patterned, takes_csv=False).check({"token": "x"}) == Checked([])


class Endless:
    """A validator whose errors never end, all at one place: only the error budget can stop the check."""

    def __init__(self) -> None:
        self.read = 0

    def iter_errors(self, value: Any) -> Iterator[ValidationError]:
        for n in itertools.count():
            self.read = n + 1
            yield ValidationError("x", validator="type", validator_value="integer", instance="a", path=[n])


def test_the_errors_read_are_bounded_whatever_the_validator_yields() -> None:
    endless = Endless()
    budget = schedule_checks.Budget(schedule_checks.MAX_STEPS)
    checked = Shape(False, {"type": "object"}, frozenset(), endless, budget).check({})  # type: ignore[arg-type]
    assert checked == Checked(["`*` must be a whole number now."], more=True)
    assert endless.read == schedule_checks.MAX_ERRORS + 1


def test_a_reason_is_bounded_in_length() -> None:
    """A field's name is the draft's own, and may be long: a reason keeps `MAX_REASON_CHARS` of it at most."""
    long = "f" * 2_000
    (reason,) = shape(schema({}, required=[long]), takes_csv=False).check({}).reasons
    assert len(reason) == schedule_checks.MAX_REASON_CHARS and reason.endswith("…")


DEEP = 300  # objects deep: past what the check's descent can follow (about 250 levels, the final review bisected)
RECURSIVE = schema({"n": {"$ref": "#/$defs/n"}, "site": {"type": "integer"}}) | {
    "$defs": {"n": {"type": "object", "properties": {"n": {"$ref": "#/$defs/n"}}}}
}


def nested(depth: int) -> bytes:
    """An input `depth` objects deep, written out: `json.dumps` would recurse as deep itself."""
    return ('{"n": ' * depth + "{}" + "}" * depth).encode()


def test_a_stored_input_nested_past_the_input_limit_is_a_break_never_descended() -> None:
    """Issue #88, ruling 5: admission refuses an input nested past 64 levels at every firing, so the check names it
    a break, under any draft, without descending it. The final review's 300-level input under a recursive draft,
    which raised `RecursionError` out of the check and was then counted unchecked, is such a break; the next input is
    still checked."""
    assert shape(RECURSIVE, takes_csv=False).check(json.loads(nested(DEEP))) == Checked([TOO_DEEP_STORED])
    deep, other = uuid.uuid4(), uuid.uuid4()
    partial, refused, unchecked = checked_all(RECURSIVE, False, [(deep, nested(DEEP)), (other, b'{"site": "a"}')])
    assert (partial, [i for i, _ in refused], unchecked) == (frozenset(), [deep, other], 0)
    assert TOO_DEEP_STORED == "Its stored input nests deeper than 64 levels: every firing is refused."


def test_the_limit_holds_under_a_draft_that_takes_any_object() -> None:
    """A permissive draft accepted a 65-level input whose every firing admission refuses: now told."""
    anything = shape({"type": "object"}, takes_csv=False)
    assert anything.check(json.loads(nested(63))) == Checked([])  # 64 levels
    assert anything.check(json.loads(nested(64))) == Checked([TOO_DEEP_STORED])  # 65
    assert shape({"type": "object"}, takes_csv=True).check(json.loads(nested(64))) == Checked([CSV])  # the draft's own


def test_a_draft_spending_many_frames_a_level_counts_an_input_within_the_limit_unchecked() -> None:
    """The review's L3: under a draft wrapping each level's reference in 6 nested `allOf`, a stored input of 64
    levels (within the limit) goes deeper than the check can follow: counted unchecked, never raised, in the check's
    worker thread as in the main thread (admission tells it "nested too deeply to check")."""
    import threading

    inner: dict[str, Any] = {"type": "object", "properties": {"n": {"$ref": "#/$defs/n"}}}
    for _ in range(6):
        inner = {"allOf": [inner]}
    wide = {"type": "object", "properties": {"n": {"$ref": "#/$defs/n"}}, "$defs": {"n": inner}}
    stored = [(uuid.uuid4(), nested(63))]  # 64 levels
    assert checked_all(wide, False, stored) == (frozenset(), [], 1)
    found: list[Any] = []
    worker = threading.Thread(target=lambda: found.append(checked_all(wide, False, stored)))
    worker.start()
    worker.join()
    assert found == [(frozenset(), [], 1)]


def test_a_depth_break_is_warned_of_as_its_own_never_as_the_drafts() -> None:
    """The review's L4: a stored input past the limit fails at every firing already, whatever is published: its
    warning says so and that the input must be replaced, apart from the schedules the draft itself would break."""
    deep, drafts = Checked([TOO_DEEP_STORED]), Checked(["`floor` is required now."])
    found = Breaks(refused=[(uuid.uuid4(), deep), (uuid.uuid4(), drafts), (uuid.uuid4(), deep)], unchecked=0)
    said = [(d.code, d.message, d.field) for d in warnings(found, takes_csv=False)]
    assert said == [
        ("schedule.input_refused", schedule_checks.REFUSED.format(n=1, s=""), "/settings/input_schema"),
        ("schedule.input_too_deep", too_deep_schedules(2), None),
    ]
    assert too_deep_schedules(1) == (
        "1 live schedule fails at every firing already: its stored input nests deeper than 64 levels. Replace its "
        "input; publishing changes nothing for it."
    )
    assert too_deep_schedules(2) == (
        "2 live schedules fail at every firing already: their stored inputs nest deeper than 64 levels. Replace their "
        "inputs; publishing changes nothing for them."
    )
