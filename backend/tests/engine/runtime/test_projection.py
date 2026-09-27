# SPDX-License-Identifier: Apache-2.0
"""`run_steps` previews (spec §8): `x-sensitive` fields are redacted wherever the schema puts them, values learned to be
sensitive are masked wherever they reappear, and oversize previews are truncated."""

from typing import Annotated, Any

import pytest
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from dewpoint.engine.runtime.projection import (
    MIN_SECRET,
    PREVIEW_BYTES,
    REDACTED,
    TRUNCATED,
    location,
    mask,
    preview,
    remember,
    sensitive_values,
)
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


class Shapes(BaseModel):
    patterned: dict[Annotated[str, StringConstraints(pattern=r"^x-")], Secret]  # patternProperties
    pair: tuple[str, Secret]  # prefixItems
    keyed: dict[Secret, int]  # propertyNames: the keys are the secret


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
    value = {"patterned": {"x-api": "k3y-one"}, "pair": ["public", "k3y-two"], "keyed": {"k3y-three": 1}}
    assert preview(value, schema) == {"patterned": {"x-api": REDACTED}, "pair": ["public", REDACTED], "keyed": REDACTED}
    assert sensitive_values(value, schema) == ["k3y-one", "k3y-two", "k3y-three"]


def test_a_recursive_schema_ends() -> None:
    tree = {
        "$defs": {"T": {"properties": {"k": {"$ref": "#/$defs/T"}, "s": {"x-sensitive": True}}}},
        "$ref": "#/$defs/T",
    }
    assert preview({"k": {"k": {"s": "x"}}, "s": "y"}, tree) == {"k": {"k": {"s": REDACTED}}, "s": REDACTED}


def test_sensitive_values_are_learned_and_masked_wherever_they_reappear() -> None:
    """Review finding: a control step copies a secret into a field no schema marks (a transform, a template, a
    message). The run remembers every sensitive value it has seen and masks it everywhere it projects."""
    learned = sensitive_values({"cred": {"user": "u", "secret": "hunter22"}, "maybe": None, "many": []}, NESTED)
    assert learned == ["hunter22"]
    secrets = remember((), learned)
    assert preview({"copy": "hunter22", "header": "Bearer hunter22!", "n": 1}, None, secrets) == {
        "copy": REDACTED,
        "header": f"Bearer {REDACTED}!",
        "n": 1,
    }
    assert mask("login failed for hunter22", secrets) == f"login failed for {REDACTED}"
    assert preview({"hunter22": 1}, None, secrets) == {REDACTED: 1}  # keys too


def test_masking_is_deterministic_and_skips_values_too_short_to_mean_anything() -> None:
    secrets = remember(remember((), ["abcd"]), ["abcdef", "xy"])  # "xy" is below MIN_SECRET
    assert MIN_SECRET == 4 and secrets == ("abcdef", "abcd")  # longest first: a longer secret is masked whole
    assert mask("abcdef abcd", secrets) == f"{REDACTED} {REDACTED}"
    assert remember(secrets, ["abcd"]) is secrets  # nothing new, nothing rebuilt


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
