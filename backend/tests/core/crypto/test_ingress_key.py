# SPDX-License-Identifier: Apache-2.0
"""The ingress key (engine 2b spec §8.3; 2b-3b task 1): an endpoint's secrets (its HMAC secret, its dedupe-digest key)
are sealed under `DEWPOINT_INGRESS_KEY`, which only ingress and the API hold, never under a tenant's data key, so
ingress authenticates and deduplicates without one. A bearer token is high-entropy, made by Dewpoint, and kept only as
its SHA-256 digest."""

import base64
import hashlib

import pytest
from cryptography.exceptions import InvalidTag

from dewpoint.core.config import Settings
from dewpoint.core.crypto import ingress

KEY = ingress.IngressKey("ingress-1", bytes(range(32)))


def settings(**given: str) -> Settings:
    return Settings(database_url="postgresql+asyncpg://x", kek_b64=base64.b64encode(bytes(32)).decode(),
                    public_origin="https://dewpoint.test", **given)  # type: ignore[arg-type]  # fmt: skip


def test_a_sealed_secret_opens_only_under_its_purpose_and_context() -> None:
    blob = KEY.seal(ingress.HMAC_SECRET, "endpoint-1", b"s3cret")
    assert b"s3cret" not in blob
    assert KEY.open(ingress.HMAC_SECRET, "endpoint-1", blob) == b"s3cret"
    for purpose, context in ((ingress.DEDUPE_KEY, "endpoint-1"), (ingress.HMAC_SECRET, "endpoint-2")):
        with pytest.raises(InvalidTag):
            KEY.open(purpose, context, blob)


def test_a_tampered_secret_is_refused() -> None:
    blob = bytearray(KEY.seal(ingress.HMAC_SECRET, "e", b"s3cret"))
    blob[-1] ^= 1
    with pytest.raises(InvalidTag):
        KEY.open(ingress.HMAC_SECRET, "e", bytes(blob))


def test_a_secret_sealed_under_another_ingress_key_is_refused_by_its_id() -> None:
    other = ingress.IngressKey("ingress-2", bytes(32))
    with pytest.raises(ingress.UnknownIngressKeyError):
        KEY.open(ingress.HMAC_SECRET, "e", other.seal(ingress.HMAC_SECRET, "e", b"x"))


@pytest.mark.parametrize(
    "blob",
    [
        b"",
        b"\x01",  # the format, then nothing (the owner's M2 review)
        b"\x02" + b"\x09ingress-1" + bytes(28),  # another format
        b"\x01\x09ingress-1",  # no nonce
        b"\x01\x20ingress-1" + bytes(28),  # an id longer than the blob says it has
        b"\x01\x00" + bytes(28),  # an empty id
        b"\x01\x02\xff\xfe" + bytes(28),  # an id that isn't UTF-8
        b"\x01\x09ingress-1" + bytes(12) + bytes(15),  # shorter than a tag
    ],
)
def test_a_malformed_sealed_secret_is_refused_as_malformed_never_an_index_error(blob: bytes) -> None:
    with pytest.raises(ingress.MalformedSecretError):
        KEY.open(ingress.HMAC_SECRET, "e", blob)
    assert issubclass(ingress.MalformedSecretError, ValueError)


def test_the_key_is_32_bytes_and_read_from_the_settings() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        ingress.IngressKey("k", bytes(16))
    with pytest.raises(ingress.IngressKeyMissingError):
        ingress.IngressKey.from_settings(settings())
    loaded = ingress.IngressKey.from_settings(
        settings(ingress_key_b64=base64.b64encode(bytes(range(32))).decode(), ingress_key_id="ingress-1")
    )
    assert loaded.open(ingress.HMAC_SECRET, "e", KEY.seal(ingress.HMAC_SECRET, "e", b"x")) == b"x"


def test_a_bearer_token_is_high_entropy_and_kept_as_its_digest() -> None:
    token = ingress.new_bearer_token()
    assert token.startswith("dwp_") and len(token) >= 40 and token != ingress.new_bearer_token()
    digest = ingress.bearer_digest(token)
    assert digest == hashlib.sha256(token.encode()).digest()
    assert ingress.bearer_matches(token, digest) and not ingress.bearer_matches(token + "x", digest)


def test_an_endpoints_secrets_are_fresh_random_bytes() -> None:
    assert len(ingress.new_hmac_secret()) >= 43 and ingress.new_hmac_secret() != ingress.new_hmac_secret()
    assert len(ingress.new_dedupe_key()) == 32 and ingress.new_dedupe_key() != ingress.new_dedupe_key()
