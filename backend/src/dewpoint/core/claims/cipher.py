# SPDX-License-Identifier: Apache-2.0
"""A claim's value, encrypted with its tenant's data key (engine 2b spec §3.1).

The tenant, the purpose `claim` and the claim's id are bound to the ciphertext, so a value moved to another claim or
another tenant doesn't open. The layout is the keyring's (`Keyring.decrypt` opens a claim), but the key comes from a
read-only `KeySource`, the codec's cache: admission seals as the dispatch role, which may only read data keys, and
nothing takes the keyring's per-tenant lock on the way."""

import os
import struct

from cryptography.exceptions import InvalidTag

from dewpoint.core.crypto.keyring import FORMAT_V1
from dewpoint.core.crypto.keys import KeySource

PURPOSE = "claim"
NONCE_BYTES = 12


class ClaimUnreadableError(Exception):
    """A claim's ciphertext that doesn't open for this tenant and id. The message is fixed: it never quotes a value."""


def _aad(tenant_id: str, claim_id: str) -> bytes:
    return f"dewpoint|{tenant_id}|{PURPOSE}|{claim_id}".encode()  # the keyring's layout: scope, purpose, context


class ClaimCipher:
    def __init__(self, keys: KeySource) -> None:
        self._keys = keys

    async def seal(self, tenant_id: str, claim_id: str, plaintext: bytes) -> bytes:
        """`plaintext` encrypted with the tenant's active key."""
        version, key = await self._keys.active(tenant_id)
        nonce = os.urandom(NONCE_BYTES)
        return FORMAT_V1 + struct.pack(">I", version) + nonce + key.encrypt(nonce, plaintext, _aad(tenant_id, claim_id))

    async def open(self, tenant_id: str, claim_id: str, blob: bytes) -> bytes:
        """The plaintext of a claim of this tenant and id, with the key version its ciphertext names."""
        if blob[:1] != FORMAT_V1 or len(blob) < 5 + NONCE_BYTES:
            raise ClaimUnreadableError("A claim's ciphertext in an unknown format.")
        (version,) = struct.unpack(">I", blob[1:5])
        key = await self._keys.get(tenant_id, version)
        try:
            return key.decrypt(blob[5 : 5 + NONCE_BYTES], blob[5 + NONCE_BYTES :], _aad(tenant_id, claim_id))
        except InvalidTag:
            raise ClaimUnreadableError("A claim that doesn't open under its tenant and id.") from None
