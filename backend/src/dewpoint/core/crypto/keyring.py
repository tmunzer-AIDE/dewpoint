# SPDX-License-Identifier: Apache-2.0
import os
import struct
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.models.keys import DataKey

FORMAT_V1 = b"\x01"


def _scope(tenant_id: uuid.UUID | None) -> str:
    return str(tenant_id) if tenant_id else "platform"


def _aad(scope: str, purpose: str, context: str) -> bytes:
    return f"dewpoint|{scope}|{purpose}|{context}".encode()


class Keyring:
    def __init__(self, keks: KekSet) -> None:
        self._keks = keks

    async def _active(self, s: AsyncSession, tenant_id: uuid.UUID | None) -> DataKey:
        scope = _scope(tenant_id)
        row = (
            await s.execute(
                select(DataKey).where(DataKey.scope_key == scope, DataKey.active.is_(True)).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            row = self._new_key(scope, tenant_id, 1)
            s.add(row)
            await s.flush()
        return row

    def _new_key(self, scope: str, tenant_id: uuid.UUID | None, version: int) -> DataKey:
        kek = self._keks.current
        wrapped = kek.wrap(AESGCM.generate_key(256), f"dek|{scope}|{version}".encode())
        return DataKey(scope_key=scope, tenant_id=tenant_id, version=version, wrapped_key=wrapped, kek_id=kek.key_id)

    def _dek(self, row: DataKey) -> AESGCM:
        kek = self._keks.get(row.kek_id)  # UnknownKekError if this process lacks the wrapping key
        return AESGCM(kek.unwrap(row.wrapped_key, f"dek|{row.scope_key}|{row.version}".encode()))

    async def encrypt(
        self, s: AsyncSession, *, tenant_id: uuid.UUID | None, purpose: str, context: str, plaintext: bytes
    ) -> bytes:
        row = await self._active(s, tenant_id)
        nonce = os.urandom(12)
        ct = self._dek(row).encrypt(nonce, plaintext, _aad(row.scope_key, purpose, context))
        return FORMAT_V1 + struct.pack(">I", row.version) + nonce + ct

    async def decrypt(
        self, s: AsyncSession, *, tenant_id: uuid.UUID | None, purpose: str, context: str, blob: bytes
    ) -> bytes:
        if blob[:1] != FORMAT_V1:
            raise ValueError("unknown ciphertext format")
        (version,) = struct.unpack(">I", blob[1:5])
        scope = _scope(tenant_id)
        row = (
            await s.execute(select(DataKey).where(DataKey.scope_key == scope, DataKey.version == version))
        ).scalar_one_or_none()
        if row is None:
            from cryptography.exceptions import InvalidTag

            raise InvalidTag()
        return self._dek(row).decrypt(blob[5:17], blob[17:], _aad(scope, purpose, context))

    async def rotate(self, s: AsyncSession, tenant_id: uuid.UUID | None) -> int:
        current = await self._active(s, tenant_id)
        await s.execute(update(DataKey).where(DataKey.id == current.id).values(active=False))
        new = self._new_key(current.scope_key, tenant_id, current.version + 1)
        s.add(new)
        await s.flush()
        return new.version

    async def rewrap_batch(self, s: AsyncSession, batch_size: int = 100) -> int:
        current = self._keks.current
        rows = (
            (
                await s.execute(
                    select(DataKey)
                    .where(DataKey.kek_id != current.key_id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            aad = f"dek|{row.scope_key}|{row.version}".encode()
            row.wrapped_key = current.wrap(self._keks.get(row.kek_id).unwrap(row.wrapped_key, aad), aad)
            row.kek_id = current.key_id
        await s.flush()
        return len(rows)

    async def kek_usage(self, s: AsyncSession) -> dict[str, int]:
        rows = await s.execute(select(DataKey.kek_id, func.count()).group_by(DataKey.kek_id))
        return {k: int(n) for k, n in rows.all()}
