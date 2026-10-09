# SPDX-License-Identifier: Apache-2.0
"""A value's schema problem said without the value (ledger M25, the owner's ruling): jsonschema's own messages quote
the instance (`'…' is too short`), and a literal written into a field marked sensitive would reach the problems panel
and the API's answers. Each case's value holds a sentinel that must never appear in what's said."""

from typing import Any

import pytest
from jsonschema import Draft202012Validator

from dewpoint.engine.graph.schema_messages import explain, problems

SECRET, NUMBER = "tok-9f2c", 41713

CASES: list[tuple[Any, Any, str]] = [
    ({"type": "integer"}, SECRET, "Must be an integer."),
    ({"type": ["string", "null"]}, NUMBER, "Must be a string or null."),
    ({"type": "object"}, [SECRET], "Must be an object."),
    ({"minLength": 12}, SECRET, "Must be at least 12 characters long."),
    ({"maxLength": 1}, SECRET, "Must be at most 1 character long."),
    ({"pattern": "^[0-9]+$"}, SECRET, "Must match the pattern `^[0-9]+$`."),
    ({"enum": ["sent", "unknown"]}, SECRET, 'Must be one of "sent", "unknown".'),
    ({"const": "sent"}, SECRET, 'Must be "sent".'),
    ({"minimum": NUMBER + 1}, NUMBER, f"Must be at least {NUMBER + 1}."),
    ({"maximum": 10}, NUMBER, "Must be at most 10."),
    ({"exclusiveMinimum": NUMBER + 5}, NUMBER, f"Must be greater than {NUMBER + 5}."),
    ({"exclusiveMaximum": 3}, NUMBER, "Must be less than 3."),
    ({"multipleOf": 5}, NUMBER, "Must be a multiple of 5."),
    ({"minItems": 3}, [SECRET], "Must have at least 3 items."),
    ({"maxItems": 1}, [SECRET, SECRET + "x"], "Must have at most 1 item."),
    ({"uniqueItems": True}, [SECRET, SECRET], "Must not repeat an item."),
    ({"contains": {"type": "integer"}}, [SECRET], "Must hold an item its schema asks for."),
    ({"minProperties": 2}, {"a": SECRET}, "Must have at least 2 properties."),
    ({"maxProperties": 0}, {"a": SECRET}, "Must have at most 0 properties."),
    ({"required": ["token", "outcome"]}, {"outcome": SECRET}, "Needs `token`."),
    (
        {"properties": {"a": {}}, "additionalProperties": False}, {"a": 1, "extra": SECRET},
        "Has a property its schema doesn't allow: `extra`.",
    ),
    ({"propertyNames": {"maxLength": 2}}, {SECRET: 1}, "Has a property whose name its schema doesn't allow."),
    ({"dependentRequired": {"user": ["password"]}}, {"user": SECRET}, "Needs `password` beside `user`."),
    ({"anyOf": [{"type": "integer"}, {"type": "boolean"}]}, SECRET, "Matches none of the forms its schema allows."),
    ({"oneOf": [{"type": "integer"}, {"type": "boolean"}]}, SECRET, "Matches none of the forms its schema allows."),
    (
        {"oneOf": [{"type": "string"}, {"minLength": 1}]}, SECRET,
        "Matches more than one of the forms its schema allows.",
    ),
    ({"not": {"type": "string"}}, SECRET, "Matches a form its schema rules out."),
    (False, SECRET, "Isn't allowed here."),
]  # fmt: skip


@pytest.mark.parametrize(("schema", "instance", "said"), CASES)
def test_a_schema_problem_is_said_without_the_value(schema: Any, instance: Any, said: str) -> None:
    errors = list(Draft202012Validator(schema).iter_errors(instance))
    assert errors, "the case must fail its schema"
    for e in errors:
        assert SECRET not in explain(e) and str(NUMBER) not in explain(e)
    assert explain(errors[0]) == said


def test_a_property_named_like_a_keyword_is_still_a_property() -> None:
    schema = {"properties": {"propertyNames": {"maxLength": 2}}}
    e = next(Draft202012Validator(schema).iter_errors({"propertyNames": SECRET}))
    assert explain(e) == "Must be at most 2 characters long."


def test_a_keyword_without_words_of_its_own_still_says_nothing_of_the_value() -> None:
    e = next(Draft202012Validator({"maxContains": 1, "contains": {}}).iter_errors([SECRET, SECRET]))
    assert SECRET not in explain(e) and explain(e) == "Doesn't satisfy its schema's `maxContains`."


@pytest.mark.parametrize(
    ("schema", "instance", "said"),
    [
        ({"required": ["a", "b"]}, {}, [((), "Needs `a`, `b`.")]),
        (
            {"dependentRequired": {"user": ["password", "otp"]}}, {"user": SECRET},
            [((), "Needs `password`, `otp` beside `user`.")],
        ),
        (
            {"propertyNames": {"maxLength": 2}}, {SECRET: 1, SECRET + "x": 2},
            [((), "Has a property whose name its schema doesn't allow.")],
        ),
        (
            {"properties": {"x": {"required": ["a", "b"]}, "y": {"required": ["a", "b"]}}}, {"x": {}, "y": {}},
            [(("x",), "Needs `a`, `b`."), (("y",), "Needs `a`, `b`.")],
        ),
    ],
)  # fmt: skip
def test_a_problem_jsonschema_reports_per_property_is_said_once_per_place(
    schema: Any, instance: Any, said: list[tuple[tuple[Any, ...], str]]
) -> None:
    # jsonschema reports these keywords once per property they find wanting; the sentence covers the keyword, so
    # each would read the same as the last.
    assert len(list(Draft202012Validator(schema).iter_errors(instance))) > len(said)
    assert problems(schema, instance) == said


def test_jsonschemas_own_words_quote_the_value() -> None:
    # The regression these guard: what `config.invalid` said before M25.
    assert SECRET in next(Draft202012Validator({"maxLength": 1}).iter_errors(SECRET)).message
