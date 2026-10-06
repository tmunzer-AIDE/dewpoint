# SPDX-License-Identifier: Apache-2.0
"""The ingress key (engine 2b spec §8.3): an endpoint's secrets — its HMAC secret and its dedupe-digest key — sealed
under `DEWPOINT_INGRESS_KEY_B64`, which only ingress and the API hold, never under a tenant's data key, so ingress
authenticates and deduplicates without one. A sealed secret names its key's id: one sealed under another key is
refused, unless the process holds that key too: during a rotation, the previous one (2b-4). A bearer token is
high-entropy, made by Dewpoint, and kept only as its SHA-256 digest."""

import base64
import hashlib
import hmac
import os
import secrets
from collections.abc import Sequence

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from dewpoint.core.config import Settings

FORMAT_V1 = b"\x01"
NONCE, TAG = 12, 16
HMAC_SECRET = "endpoint.hmac"  # noqa: S105 - a purpose's name, not a credential (an endpoint's id is the context)
DEDUPE_KEY = "endpoint.dedupe"
BEARER_PREFIX = "dwp_"


class IngressKeyMissingError(LookupError):
    """A process that needs the ingress key (ingress, the API's endpoint routes) was started without one."""


class UnknownIngressKeyError(LookupError):
    """A secret sealed under an ingress key this process doesn't hold."""


class MalformedSecretError(ValueError):
    """Bytes that aren't a sealed secret's layout: format, id length, id, nonce, then at least a tag."""


def _checked(key_id: str, key: bytes) -> AESGCM:
    if len(key) != 32:
        raise ValueError("the ingress key must be 32 bytes")
    if not 0 < len(key_id.encode()) < 256:
        raise ValueError("the ingress key's id must be 1 to 255 bytes")
    return AESGCM(key)


class IngressKey:
    """The current ingress key, which seals, and during a rotation the previous one, which only opens."""

    def __init__(self, key_id: str, key: bytes, previous: Sequence[tuple[str, bytes]] = ()) -> None:
        self.key_id, self._aes = key_id, _checked(key_id, key)
        self._held = {key_id: self._aes} | {kid: _checked(kid, raw) for kid, raw in previous}
        if len(self._held) != len(previous) + 1:
            raise ValueError("ingress key ids must be unique")

    @property
    def key_ids(self) -> frozenset[str]:
        return frozenset(self._held)

    @staticmethod
    def _aad(purpose: str, context: str) -> bytes:
        return f"dewpoint|ingress|{purpose}|{context}".encode()

    def seal(self, purpose: str, context: str, plaintext: bytes) -> bytes:
        kid, nonce = self.key_id.encode(), os.urandom(NONCE)
        sealed = self._aes.encrypt(nonce, plaintext, self._aad(purpose, context))
        return FORMAT_V1 + bytes([len(kid)]) + kid + nonce + sealed

    def open(self, purpose: str, context: str, blob: bytes) -> bytes:
        """Raises MalformedSecretError for bytes that aren't the layout, UnknownIngressKeyError for another key's
        secret, and InvalidTag for one that doesn't authenticate."""
        if len(blob) < 2 or blob[:1] != FORMAT_V1:
            raise MalformedSecretError("not a sealed secret of a known format")
        size = blob[1]
        if size == 0 or len(blob) < 2 + size + NONCE + TAG:
            raise MalformedSecretError("a sealed secret too short for its layout")
        try:
            kid = blob[2 : 2 + size].decode()
        except UnicodeDecodeError:
            raise MalformedSecretError("a sealed secret's key id isn't UTF-8") from None
        held = self._held.get(kid)
        if held is None:
            raise UnknownIngressKeyError(kid)
        rest = blob[2 + size :]
        return held.decrypt(rest[:NONCE], rest[NONCE:], self._aad(purpose, context))

    @classmethod
    def from_settings(cls, settings: Settings) -> "IngressKey":
        if not settings.ingress_key_b64:
            raise IngressKeyMissingError("DEWPOINT_INGRESS_KEY_B64 is required by ingress and the API's endpoints")
        return cls(settings.ingress_key_id, base64.b64decode(settings.ingress_key_b64), previous_of(settings))


def previous_of(settings: object) -> list[tuple[str, bytes]]:
    """The previous ingress key a rollout configures (`DEWPOINT_INGRESS_KEY_PREVIOUS_B64` and `_ID`), if any."""
    raw, kid = getattr(settings, "ingress_key_previous_b64", None), getattr(settings, "ingress_key_previous_id", None)
    if not raw:
        return []
    if not kid:
        raise ValueError("DEWPOINT_INGRESS_KEY_PREVIOUS_ID is required with DEWPOINT_INGRESS_KEY_PREVIOUS_B64")
    return [(kid, base64.b64decode(raw))]


def new_bearer_token() -> str:
    """256 random bits: what a sender presents, shown once; Dewpoint keeps only its digest."""
    return BEARER_PREFIX + secrets.token_urlsafe(32)


def new_hmac_secret() -> str:
    return secrets.token_urlsafe(32)


def new_dedupe_key() -> bytes:
    return os.urandom(32)


def bearer_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def bearer_matches(token: str, digest: bytes) -> bool:
    """In constant time, whatever the token."""
    return hmac.compare_digest(bearer_digest(token), digest)
