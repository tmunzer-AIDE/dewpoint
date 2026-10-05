# SPDX-License-Identifier: Apache-2.0
"""Authentication (the owner's ruling 2): an HMAC-SHA256 under the endpoint's secret of `<timestamp>.<the exact raw
body>`, its timestamp within the endpoint's tolerance, or a bearer token matching the endpoint's digest; compared in
constant time. Anything else is a failure, never an error."""

import hashlib
import hmac
import os
import uuid
from dataclasses import replace

from starlette.datastructures import Headers

from dewpoint.apps.ingress.auth import authenticate
from dewpoint.apps.ingress.endpoints import Endpoint
from dewpoint.core.crypto.ingress import HMAC_SECRET, IngressKey, bearer_digest

KEY = IngressKey("ingress-1", os.urandom(32))
ID = uuid.uuid4()
SECRET = b"s3cret-of-the-endpoint"
BODY = b'{"topic": "alarms", "events": [{"id": 1}]}'
NOW = 1_800_000_000.0

HMAC = Endpoint(
    id=ID, tenant_id=uuid.uuid4(), enabled=True, tenant_active=True, auth_kind="hmac", bearer_digest=None,
    hmac_secret=KEY.seal(HMAC_SECRET, str(ID), SECRET), signature_header="x-signature",
    timestamp_header="x-timestamp", tolerance_s=300, allowlist=(), body_limit=1024 * 1024, id_source="none",
    id_pointer=None, id_header=None, events_pointer=None, dedupe_key=b"", key_version=1, public_key=b"\0" * 32,
)  # fmt: skip
BEARER = replace(HMAC, auth_kind="bearer", hmac_secret=None, bearer_digest=bearer_digest("dwp_token"))


def _signed(stamp: str, body: bytes = BODY, secret: bytes = SECRET) -> Headers:
    signature = hmac.new(secret, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return Headers({"x-timestamp": stamp, "x-signature": signature})


def test_a_signature_of_the_exact_bytes_within_the_tolerance_authenticates() -> None:
    assert authenticate(HMAC, _signed(str(int(NOW))), BODY, NOW, KEY)
    assert authenticate(HMAC, _signed(str(int(NOW) - 300)), BODY, NOW, KEY)
    assert authenticate(HMAC, _signed(str(int(NOW) + 300)), BODY, NOW, KEY)


def test_the_signature_may_be_upper_case_or_prefixed() -> None:
    headers = _signed(str(int(NOW)))
    assert authenticate(HMAC, Headers({**headers, "x-signature": headers["x-signature"].upper()}), BODY, NOW, KEY)
    assert authenticate(HMAC, Headers({**headers, "x-signature": "sha256=" + headers["x-signature"]}), BODY, NOW, KEY)


def test_a_timestamp_outside_the_tolerance_fails_a_replay_included() -> None:
    assert not authenticate(HMAC, _signed(str(int(NOW) - 301)), BODY, NOW, KEY)
    assert not authenticate(HMAC, _signed(str(int(NOW) + 301)), BODY, NOW, KEY)


def test_other_bytes_another_secret_or_a_moved_timestamp_fail() -> None:
    stamp = str(int(NOW))
    assert not authenticate(HMAC, _signed(stamp), BODY + b" ", NOW, KEY)  # reformatted: other bytes
    assert not authenticate(HMAC, _signed(stamp, secret=b"another"), BODY, NOW, KEY)
    moved = Headers({**_signed(stamp), "x-timestamp": str(int(NOW) - 1)})
    assert not authenticate(HMAC, moved, BODY, NOW, KEY)


def test_missing_or_odd_headers_fail_without_an_error() -> None:
    stamp = str(int(NOW))
    signature = _signed(stamp)["x-signature"]
    for headers in (
        {},
        {"x-timestamp": stamp},
        {"x-signature": signature},
        {"x-timestamp": f" {stamp}", "x-signature": signature},
        {"x-timestamp": "1e9", "x-signature": signature},
        {"x-timestamp": "-" + stamp, "x-signature": signature},
        {"x-timestamp": "9" * 400, "x-signature": signature},
        {"x-timestamp": stamp[:-1] + "²", "x-signature": signature},  # a digit to `str.isdigit`, but not ASCII
        {"x-timestamp": stamp, "x-signature": "é" * 64},
        {"x-timestamp": stamp, "x-signature": ""},
    ):
        assert not authenticate(HMAC, Headers(headers), BODY, NOW, KEY), headers


def test_a_secret_this_process_cannot_open_fails() -> None:
    other = IngressKey("ingress-2", os.urandom(32))
    endpoint = replace(HMAC, hmac_secret=other.seal(HMAC_SECRET, str(ID), SECRET))
    assert not authenticate(endpoint, _signed(str(int(NOW))), BODY, NOW, KEY)
    swapped = replace(HMAC, hmac_secret=KEY.seal(HMAC_SECRET, str(uuid.uuid4()), SECRET))  # another endpoint's
    assert not authenticate(swapped, _signed(str(int(NOW))), BODY, NOW, KEY)
    for malformed in (b"", b"\x01", b"\x01\x09ingress-1", b"\x02" + bytes(40)):  # truncated, another format
        assert not authenticate(replace(HMAC, hmac_secret=malformed), _signed(str(int(NOW))), BODY, NOW, KEY)


def test_a_bearer_token_authenticates_by_its_digest() -> None:
    assert authenticate(BEARER, Headers({"authorization": "Bearer dwp_token"}), BODY, NOW, KEY)
    assert authenticate(BEARER, Headers({"authorization": "bearer dwp_token"}), BODY, NOW, KEY)
    for value in ("Bearer dwp_other", "Basic dwp_token", "Bearer", "dwp_token", "Bearer  ", "Bearer é"):
        assert not authenticate(BEARER, Headers({"authorization": value}), BODY, NOW, KEY), value
    assert not authenticate(BEARER, Headers({}), BODY, NOW, KEY)


def test_a_signed_request_doesnt_pass_a_bearer_endpoint_nor_a_token_an_hmac_one() -> None:
    assert not authenticate(BEARER, _signed(str(int(NOW))), BODY, NOW, KEY)
    assert not authenticate(HMAC, Headers({"authorization": "Bearer dwp_token"}), BODY, NOW, KEY)
