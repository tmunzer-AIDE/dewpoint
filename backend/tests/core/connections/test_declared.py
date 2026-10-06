# SPDX-License-Identifier: Apache-2.0
"""A connection type as a synced manifest declares it (plugins-3 D11): what the API validates, lists and computes from
data alone, without running plugin code. The expected values are the ones `core` produced for `mist` before 3a-2."""

import uuid

import pytest

from dewpoint.core.connections.declared import DeclaredType, InvalidValueError
from dewpoint.core.ratelimit.buckets import Scope
from dewpoint.plugins.mist import PLUGIN

ORG = "6a1d6e2f-3c4b-4a5d-9e8f-0123456789ab"
TOKEN = "tok_" + "a" * 36
MIST = DeclaredType.from_manifest("mist", PLUGIN.manifest()["connection_types"][0])


def test_a_valid_config_and_secret_are_kept_as_written() -> None:
    assert MIST.config({"cloud": "emea_01", "org_id": ORG}) == {"cloud": "emea_01", "org_id": ORG}
    assert MIST.secret({"api_token": TOKEN}) == {"api_token": TOKEN}


@pytest.mark.parametrize(
    ("config", "fields"),
    [
        ({"cloud": "evil.example.com", "org_id": ORG}, ["cloud"]),
        ({"cloud": "emea_01", "org_id": ORG, "host": "evil.example.com"}, ["host"]),
        ({"cloud": "emea_01"}, ["org_id"]),
        ({"cloud": "emea_01", "org_id": "not-a-uuid"}, ["org_id"]),
        ({"cloud": "emea_01", "org_id": ORG.upper()}, ["org_id"]),  # only the canonical form: keys must match
        ({"cloud": "emea_01", "org_id": "{" + ORG + "}"}, ["org_id"]),
        ("not an object", [""]),
    ],
)
def test_an_invalid_config_names_its_fields(config: object, fields: list[str]) -> None:
    with pytest.raises(InvalidValueError) as raised:
        MIST.config(config)
    assert raised.value.fields == fields


@pytest.mark.parametrize(
    ("secret", "fields"),
    [
        ({"api_token": "short"}, ["api_token"]),
        ({"api_token": TOKEN, "extra": TOKEN}, ["extra"]),
        ({"api_token": 12345678901234567890123}, ["api_token"]),
        ({}, ["api_token"]),
    ],
)
def test_an_invalid_secret_names_its_fields_never_its_values(secret: object, fields: list[str]) -> None:
    with pytest.raises(InvalidValueError) as raised:
        MIST.secret(secret)
    assert raised.value.fields == fields
    assert TOKEN not in str(raised.value) and "short" not in str(raised.value)


def test_the_base_url_comes_from_the_host_map() -> None:
    assert MIST.base_url({"cloud": "emea_01", "org_id": ORG}) == "https://api.eu.mist.com"
    assert MIST.base_url({"cloud": "nowhere", "org_id": ORG}) is None


def test_the_credentials_header_is_filled_from_the_secret() -> None:
    assert MIST.credentials({"api_token": TOKEN}) == {"Authorization": f"Token {TOKEN}"}


def test_scope_keys_are_the_ones_core_computed() -> None:
    def mac(credential: str) -> str:
        return f"mac({credential})"

    assert MIST.scopes({"cloud": "emea_01", "org_id": ORG}, {"api_token": TOKEN}, mac) == [
        Scope(f"mist.org:emea_01:{ORG}", 50.0, 1.25),
        Scope(f"mist.token:mac({TOKEN})", 50.0, 1.25),
    ]


def test_the_listing_keeps_the_shape_the_web_app_reads() -> None:
    listed = MIST.listing()
    assert {k: v for k, v in listed.items() if k != "config_schema"} == {
        "key": "mist",
        "label": "Juniper Mist",
        "secret_fields": ["api_token"],
        "clouds": PLUGIN.manifest()["connection_types"][0]["host"]["hosts"],
    }
    assert listed["config_schema"]["properties"]["org_id"] == {"format": "uuid", "title": "Org Id", "type": "string"}


def test_a_uuid_format_is_checked_only_where_declared() -> None:
    kind = DeclaredType.from_manifest(
        "demo",
        {
            "key": "demo",
            "label": "Demo",
            "config_schema": {"type": "object", "additionalProperties": False,
                              "properties": {"name": {"type": "string"}}},
            "secret_schema": {"type": "object", "additionalProperties": False, "properties": {}},
            "auth": None,
            "host": None,
            "rate_scopes": [],
            "verify": False,
        },
    )  # fmt: skip
    upper = str(uuid.uuid4()).upper()
    assert kind.config({"name": upper}) == {"name": upper}
    assert kind.base_url({"name": "x"}) is None and kind.credentials({}) == {}


def test_credentials_name_fields_and_never_format_them() -> None:
    """A template is filled field by field (plugins-3, the 3a-2 review's finding 3): a format spec or a conversion is
    refused at sync, and filling never formats, so no failure can quote the secret."""
    auth = {"kind": "header", "header": "X", "template": "{api_token:>9}"}
    kind = DeclaredType.from_manifest("mist", {**PLUGIN.manifest()["connection_types"][0], "auth": auth})
    with pytest.raises(InvalidValueError) as raised:
        kind.credentials({"api_token": TOKEN})
    assert TOKEN not in str(raised.value)
