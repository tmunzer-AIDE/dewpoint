# SPDX-License-Identifier: Apache-2.0
"""`run_steps` previews (spec §8): `x-sensitive` fields are redacted wherever the schema puts them, and oversize
previews are truncated. A sensitive value never reaches the workflow (engine 2b spec §3.6): the project activity masks
every row against the run tree's secret index, with the matcher (§3.7)."""

from typing import Annotated, Any

import pytest
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from dewpoint.engine.matcher import Matcher, masked
from dewpoint.engine.runtime.projection import PREVIEW_BYTES, REDACTED, TRUNCATED, location, preview
from dewpoint.engine.sensitive import MIN_SECRET
from dewpoint.sdk import Node, node_manifest, sensitive

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "token": {"type": "string", "x-sensitive": True},
        "devices": {"type": "array", "items": {"type": "object", "properties": {"psk": {"x-sensitive": True}}}},
        "headers": {"type": "object", "additionalProperties": {"type": "string", "x-sensitive": True}},
        "name": {"type": "string"},
    },
}


class Cred(BaseModel):
    user: str
    secret: str = sensitive()


class NestedOutput(BaseModel):
    cred: Cred
    maybe: Cred | None
    many: list[Cred]


class Nested(Node):
    type = "testkit.nested"
    version = 1
    title = "Nested"
    Output = NestedOutput

    async def run(self, ctx: Any, config: Any) -> NestedOutput:
        raise NotImplementedError


NESTED = node_manifest(Nested)["output_schema"]  # $defs, $ref and anyOf, as pydantic writes nested models


def test_sensitive_fields_are_redacted_wherever_the_schema_marks_them() -> None:
    value = {
        "token": "t0p",
        "devices": [{"psk": "a", "id": 1}, {"id": 2}],
        "headers": {"Authorization": "Bearer x"},
        "name": "ap-1",
        "extra": {"token": "not declared"},  # only the schema decides
    }
    assert preview(value, SCHEMA) == {
        "token": REDACTED,
        "devices": [{"psk": REDACTED, "id": 1}, {"id": 2}],
        "headers": {"Authorization": REDACTED},
        "name": "ap-1",
        "extra": {"token": "not declared"},
    }


def test_redaction_follows_references_and_unions() -> None:
    """Review finding: a nested model's sensitive field sits behind `$ref`, and an optional one behind `anyOf`."""
    value = {
        "cred": {"user": "u", "secret": "s1"},
        "maybe": {"user": "v", "secret": "s2"},
        "many": [{"user": "w", "secret": "s3"}],
    }
    assert preview(value, NESTED) == {
        "cred": {"user": "u", "secret": REDACTED},
        "maybe": {"user": "v", "secret": REDACTED},
        "many": [{"user": "w", "secret": REDACTED}],
    }
    assert preview({"cred": None, "maybe": None, "many": []}, NESTED) == {"cred": None, "maybe": None, "many": []}


Secret = Annotated[str, sensitive()]


class Overlap(BaseModel):
    """A declared field that a sensitive pattern also covers: JSON Schema applies both to it."""

    model_config = ConfigDict(json_schema_extra={"patternProperties": {"^x-": {"type": "string", "x-sensitive": True}}})
    token: str = Field(alias="x-token")
    name: str


class Shapes(BaseModel):
    patterned: dict[Annotated[str, StringConstraints(pattern=r"^x-")], Secret]  # patternProperties
    pair: tuple[str, Secret]  # prefixItems
    keyed: dict[Secret, int]  # propertyNames: the keys are the secret
    overlap: Overlap  # properties and patternProperties at once


class ShapesNode(Node):
    type = "testkit.shapes"
    version = 1
    title = "Shapes"
    Output = Shapes

    async def run(self, ctx: Any, config: Any) -> Shapes:
        raise NotImplementedError


def test_redaction_covers_patterned_maps_tuples_and_sensitive_keys() -> None:
    """Checkpoint-1 finding: a patterned-key map's values sit under `patternProperties`, which redaction didn't read,
    so the credential showed and was never learned. Tuple positions (`prefixItems`) and sensitive keys
    (`propertyNames`) had the same gap."""
    schema = node_manifest(ShapesNode)["output_schema"]
    value = {
        "patterned": {"x-api": "k3y-one"},
        "pair": ["public", "k3y-two"],
        "keyed": {"k3y-three": 1},
        "overlap": {"x-token": "k3y-four", "name": "n"},  # checkpoint-1 re-review: a declared key a pattern covers
    }
    assert preview(value, schema) == {
        "patterned": {"x-api": REDACTED},
        "pair": ["public", REDACTED],
        "keyed": REDACTED,
        "overlap": {"x-token": REDACTED, "name": REDACTED},  # every pattern applies, matched or not: over-redaction
    }


def test_a_recursive_schema_ends() -> None:
    tree = {
        "$defs": {"T": {"properties": {"k": {"$ref": "#/$defs/T"}, "s": {"x-sensitive": True}}}},
        "$ref": "#/$defs/T",
    }
    assert preview({"k": {"k": {"s": "x"}}, "s": "y"}, tree) == {"k": {"k": {"s": REDACTED}}, "s": REDACTED}


def test_a_known_secret_is_masked_wherever_it_reappears() -> None:
    """Review finding: a control step copies a secret into a field no schema marks (a transform, a template, a
    message). The project activity masks every row against the run tree's index, in strings and keys, at any depth."""
    secrets = Matcher(["hunter22"])
    row = {"copy": "hunter22", "header": "Bearer hunter22!", "n": 1, "hunter22": [{"m": "login failed for hunter22"}]}
    assert masked(row, secrets, REDACTED) == {
        "copy": REDACTED,
        "header": f"Bearer {REDACTED}!",
        "n": 1,
        REDACTED: [{"m": f"login failed for {REDACTED}"}],
    }


def test_masking_takes_the_longest_secret_and_skips_values_too_short_to_mean_anything() -> None:
    secrets = Matcher(["abcd", "abcdef", "xy"])  # "xy" is below MIN_SECRET
    assert MIN_SECRET == 4 and secrets.strings == ("abcd", "abcdef")
    assert masked("abcdef abcd xy", secrets, REDACTED) == f"{REDACTED} {REDACTED} xy"


def test_a_preview_over_8_kib_is_truncated() -> None:
    assert preview({"s": "x" * (PREVIEW_BYTES - 8)}) == {"s": "x" * (PREVIEW_BYTES - 8)}  # exactly 8 KiB
    assert preview({"s": "x" * (PREVIEW_BYTES - 7)}) == TRUNCATED
    assert preview({"token": "x" * PREVIEW_BYTES}, SCHEMA) == {"token": REDACTED}  # measured after redaction


def test_a_value_canonical_json_refuses_is_truncated() -> None:
    assert preview({"f": float("nan")}) == TRUNCATED


class Item(BaseModel):
    name: str


class Located(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headers: dict[int, int]
    tags: dict[str, int]
    items: list[Item]
    pair: tuple[int, str]
    maybe: Item | None
    name: str


def test_a_location_keeps_only_what_the_schema_declares_at_that_place() -> None:
    """Review findings: a location part can come from the data. A numeric key of `dict[int, …]` looks like a list
    index, and a text key can match a field declared elsewhere. Walking the schema tells them apart."""
    data = {
        "headers": {"428319": "x"},  # a numeric key
        "tags": {"name": "x"},  # a key that matches a field declared elsewhere
        "items": [{"name": 1}],
        "pair": [1, 2],
        "maybe": {"name": 3},
        "name": 4,
        "hunter22": 1,  # an unknown key
    }
    with pytest.raises(ValidationError) as e:
        Located.model_validate(data)
    schema = Located.model_json_schema()
    assert [location(err["loc"], schema) for err in e.value.errors()] == [
        "headers.*",
        "tags.*",
        "items.0.name",
        "pair.1",
        "maybe.name",
        "name",
        "*",
    ]
    assert location((), schema) == "(root)"
