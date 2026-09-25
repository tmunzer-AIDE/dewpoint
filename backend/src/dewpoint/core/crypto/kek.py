# SPDX-License-Identifier: Apache-2.0
import base64
import os
from collections.abc import Sequence

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from dewpoint.core.config import Settings


class UnknownKekError(LookupError):
    pass


class Kek:
    def __init__(self, key_id: str, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("KEK must be 32 bytes")
        self.key_id, self._aes = key_id, AESGCM(key)

    def wrap(self, dek: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aes.encrypt(nonce, dek, aad)

    def unwrap(self, blob: bytes, aad: bytes) -> bytes:
        return self._aes.decrypt(blob[:12], blob[12:], aad)


class KekSet:
    """The current KEK wraps new data keys; previous KEKs only unwrap (used during a rollout)."""

    def __init__(self, current: Kek, previous: Sequence[Kek] = ()) -> None:
        self.current = current
        self._by_id = {k.key_id: k for k in (*previous, current)}
        if len(self._by_id) != len(previous) + 1:
            raise ValueError("KEK ids must be unique")

    def get(self, kek_id: str) -> Kek:
        try:
            return self._by_id[kek_id]
        except KeyError:
            raise UnknownKekError(kek_id) from None

    @classmethod
    def from_settings(cls, settings: Settings) -> "KekSet":
        current = Kek(settings.kek_id, base64.b64decode(settings.kek_b64))
        previous = []
        if settings.kek_previous_b64:
            if not settings.kek_previous_id:
                raise ValueError("DEWPOINT_KEK_PREVIOUS_ID is required with DEWPOINT_KEK_PREVIOUS_B64")
            previous.append(Kek(settings.kek_previous_id, base64.b64decode(settings.kek_previous_b64)))
        return cls(current, previous)
