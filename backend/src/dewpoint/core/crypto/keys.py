# SPDX-License-Identifier: Apache-2.0
"""Tenants' data keys, read-only and cached in the process (engine 2b spec §6.3): what the payload codec and the claim
cipher encrypt with. Nothing here creates a key: a tenant gets one when it's created."""

import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.crypto.kek import UnknownKekError
from dewpoint.core.crypto.keyring import Keyring, NoKeyError
from dewpoint.core.db import tenant_scope, unavailable


def digest_key_of(raw: bytes, tenant_id: str) -> bytes:
    """The key a tenant's run requests are digested with (engine 2b spec §7.2), derived from its data key `raw`: never
    the data key itself, and bound to the tenant and to this one use."""
    info = f"dewpoint|{tenant_id}|request-digest".encode()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(raw)


def key_unreadable(e: BaseException | None) -> bool:
    """Whether `e` is how reading a tenant's key fails with nothing wrong in the code (a `KeySource`'s contract): no
    such key (`NoKeyError`), its KEK not configured (`UnknownKekError`), a stored key that doesn't unwrap under its KEK
    (`InvalidTag`), or a keyring database that doesn't answer (`core.db.unavailable`). A bug in the reader is none."""
    if e is None:
        return False
    return isinstance(e, (NoKeyError, UnknownKekError, InvalidTag)) or unavailable(e)


class KeySource(Protocol):
    """A tenant's data keys, by version. Read-only: neither the codec nor the claim cipher creates a key (a tenant
    gets one when it's created). A key that can't be read raises what `key_unreadable` accepts."""

    async def active(self, tenant_id: str) -> tuple[int, AESGCM]: ...

    async def get(self, tenant_id: str, version: int) -> AESGCM: ...

    async def digest_key(self, tenant_id: str, version: int | None) -> tuple[int, bytes]:
        """The tenant's request-digest key derived from its data key of `version` (its active one when None), with
        that version."""
        ...


class KeyringKeys:
    """Tenants' data keys from the keyring, read-only, cached unwrapped in this process and nowhere else: at most
    `size` of them, each for at most `ttl_s` seconds, so a rotation takes effect within `ttl_s`. A missing key is
    never cached: a tenant created after this process started is served at once (spec §6.3).

    An expired key is never used, even while the database doesn't answer (the owner's ruling, 2b-1a's review): the
    rotation bound and the retirement floor (§6.4) stay exact, and a payload whose key can't be read again fails."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        keyring: Keyring,
        *,
        size: int = 1024,
        ttl_s: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessionmaker, self._keyring = sessionmaker, keyring
        self._size, self._ttl_s, self._clock = size, ttl_s, clock
        # Each entry: when it expires, the key's version, the data key, and the request-digest key derived from it.
        self._cache: OrderedDict[tuple[str, int | None], tuple[float, int, AESGCM, bytes]] = OrderedDict()

    async def active(self, tenant_id: str) -> tuple[int, AESGCM]:
        _, found, key, _ = await self._read(tenant_id, None)
        return found, key

    async def get(self, tenant_id: str, version: int) -> AESGCM:
        return (await self._read(tenant_id, version))[2]

    async def digest_key(self, tenant_id: str, version: int | None) -> tuple[int, bytes]:
        _, found, _, derived = await self._read(tenant_id, version)
        return found, derived

    async def _read(self, tenant_id: str, version: int | None) -> tuple[float, int, AESGCM, bytes]:
        now = self._clock()
        hit = self._cache.get((tenant_id, version))
        if hit is not None and hit[0] > now:
            self._cache.move_to_end((tenant_id, version))
            return hit
        tenant = uuid.UUID(tenant_id)
        async with self._sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            found, raw = await self._keyring.read_dek(s, tenant, version)
        entry = (now + self._ttl_s, found, AESGCM(raw), digest_key_of(raw, tenant_id))
        for k in {(tenant_id, version), (tenant_id, found)}:
            self._cache[k] = entry
            self._cache.move_to_end(k)
        while len(self._cache) > self._size:
            self._cache.popitem(last=False)
        return entry
