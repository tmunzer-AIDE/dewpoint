# SPDX-License-Identifier: Apache-2.0
"""A secret-URL type at run time, whatever its declaration lets through (the 3c-1 review, findings 1 and 2): the
SDK and the catalog check a pattern's text, which can't prove what it matches, so the runtime holds the rules itself.
A secret URL is https, both where it's accepted and where it's read; a scope's part of a secret is a group that took
part in the match and isn't empty, else the secret is refused before any request."""

import copy
from typing import Any

import pytest

from dewpoint.core.connections.declared import DeclaredType, InvalidValueError
from tests.support.plugins.hookkit import HOOKKIT

URL = "https://hooks.test/v1/spaces/abc/messages?key=abcdefgh"


def declared(pattern: str | None = None, secret_pattern: str | None = None) -> DeclaredType:
    manifest: dict[str, Any] = copy.deepcopy(HOOKKIT.manifest()["connection_types"][0])
    if pattern is not None:
        manifest["host"]["pattern"] = pattern
    if secret_pattern is not None:
        manifest["rate_scopes"][0]["secret_pattern"] = secret_pattern
    return DeclaredType.from_manifest("hookkit", manifest)


def test_an_alternation_cant_admit_plain_http() -> None:
    """`https://x|http://.*` starts with https as text; the runtime still takes https URLs only."""
    kind = declared(pattern=r"https://hooks\.test/spaces/abc/x|http://.*/spaces/abc/.*")
    with pytest.raises(InvalidValueError) as raised:
        kind.secret({"webhook_url": "http://10.0.0.5:8080/spaces/abc/admin"})
    assert raised.value.fields == ["webhook_url"]
    ok = "https://hooks.test/spaces/abc/x"
    assert kind.secret({"webhook_url": ok}) == {"webhook_url": ok}


@pytest.mark.parametrize("url", ["http://hooks.test/x", "HTTP://hooks.test/x", "ftp://hooks.test/x", ""])
def test_a_secret_urls_base_is_https_or_none(url: str) -> None:
    assert declared().base_url({}, {"webhook_url": url}) is None
    assert declared().base_url({}, {"webhook_url": URL}) == URL


@pytest.mark.parametrize(
    "secret_pattern",
    [
        r"/spaces/(zzz)?",  # the group takes no part for this URL
        r"/spaces/()",  # empty
    ],
)
def test_a_scope_group_that_takes_no_part_refuses_the_secret(secret_pattern: str) -> None:
    kind = declared(secret_pattern=secret_pattern)
    with pytest.raises(InvalidValueError) as raised:
        kind.secret({"webhook_url": URL})
    assert raised.value.fields == ["webhook_url"]
    with pytest.raises(InvalidValueError):
        kind.scopes({}, {"webhook_url": URL}, lambda v: f"mac({v})")


def test_a_scope_group_that_takes_part_keys_the_scope() -> None:
    [scope] = declared().scopes({}, {"webhook_url": URL}, lambda v: f"mac({v})")
    assert scope.key == "hookkit.space:mac(abc)"
