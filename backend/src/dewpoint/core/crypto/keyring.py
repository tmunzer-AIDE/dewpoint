# SPDX-License-Identifier: Apache-2.0
import os
import struct
import uuid
from collections.abc import Sequence
from typing import Any, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.models.keys import DataKey, PlatformKey

FORMAT_V1 = b"\x01"
type AnyKey = DataKey | PlatformKey


def _scope(tenant_id: uuid.UUID | None) -> str:
    return str(tenant_id) if tenant_id else "platform"


def _aad(scope: str, purpose: str, context: str) -> bytes:
    return f"dewpoint|{scope}|{purpose}|{context}".encode()


def _dek_aad(row: AnyKey) -> bytes:
    scope = str(row.tenant_id) if isinstance(row, DataKey) else "platform"
    return f"dek|{scope}|{row.version}".encode()


def _scope_filter(tenant_id: uuid.UUID | None) -> tuple[type[AnyKey], list[Any]]:
    """Tenant keys live in RLS-scoped data_keys; the platform key in the narrowly granted platform_keys."""
    if tenant_id is None:
        return PlatformKey, []
    return DataKey, [DataKey.tenant_id == tenant_id]


class Keyring:
    def __init__(self, keks: KekSet) -> None:
        self._keks = keks

    async def _active(self, s: AsyncSession, tenant_id: uuid.UUID | None) -> AnyKey:
        # Serialize first-use creation and rotation per scope until commit; FOR UPDATE alone can't lock a
        # row that doesn't exist yet, so two first uses would both insert version 1.
        await s.execute(
            text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"dewpoint:dek:{_scope(tenant_id)}"}
        )
        model, where = _scope_filter(tenant_id)
        found = (
            await s.execute(select(model).where(*where, model.active.is_(True)).with_for_update())
        ).scalar_one_or_none()
        row = cast(AnyKey | None, found)
        if row is None:
            row = self._new_key(tenant_id, 1)
            s.add(row)
            await s.flush()
        return row

    def _new_key(self, tenant_id: uuid.UUID | None, version: int) -> AnyKey:
        kek = self._keks.current
        row: AnyKey = (
            PlatformKey(version=version) if tenant_id is None else DataKey(tenant_id=tenant_id, version=version)
        )
        row.wrapped_key = kek.wrap(AESGCM.generate_key(256), _dek_aad(row))
        row.kek_id = kek.key_id
        return row

    def _dek(self, row: AnyKey) -> AESGCM:
        kek = self._keks.get(row.kek_id)  # UnknownKekError if this process lacks the wrapping key
        return AESGCM(kek.unwrap(row.wrapped_key, _dek_aad(row)))

    async def encrypt(
        self, s: AsyncSession, *, tenant_id: uuid.UUID | None, purpose: str, context: str, plaintext: bytes
    ) -> bytes:
        row = await self._active(s, tenant_id)
        nonce = os.urandom(12)
        ct = self._dek(row).encrypt(nonce, plaintext, _aad(_scope(tenant_id), purpose, context))
        return FORMAT_V1 + struct.pack(">I", row.version) + nonce + ct

    async def decrypt(
        self, s: AsyncSession, *, tenant_id: uuid.UUID | None, purpose: str, context: str, blob: bytes
    ) -> bytes:
        if blob[:1] != FORMAT_V1:
            raise ValueError("unknown ciphertext format")
        (version,) = struct.unpack(">I", blob[1:5])
        model, where = _scope_filter(tenant_id)
        found = (await s.execute(select(model).where(*where, model.version == version))).scalar_one_or_none()
        row = cast(AnyKey | None, found)
        if row is None:  # missing, or invisible under RLS: indistinguishable from a bad tag on purpose
            raise InvalidTag()
        return self._dek(row).decrypt(blob[5:17], blob[17:], _aad(_scope(tenant_id), purpose, context))

    async def rotate(self, s: AsyncSession, tenant_id: uuid.UUID | None) -> int:
        current = await self._active(s, tenant_id)
        await s.execute(update(type(current)).where(type(current).id == current.id).values(active=False))
        new = self._new_key(tenant_id, current.version + 1)
        s.add(new)
        await s.flush()
        return new.version

    async def rewrap_batch(self, s: AsyncSession, batch_size: int = 100) -> int:
        """Rewrap up to batch_size keys not wrapped by the current KEK. Run as a key-admin role."""
        current = self._keks.current
        done = 0
        for model in (DataKey, PlatformKey):
            if done >= batch_size:
                break
            q = select(model).where(model.kek_id != current.key_id).limit(batch_size - done)
            rows = cast(Sequence[AnyKey], (await s.execute(q.with_for_update(skip_locked=True))).scalars().all())
            for row in rows:
                aad = _dek_aad(row)
                row.wrapped_key = current.wrap(self._keks.get(row.kek_id).unwrap(row.wrapped_key, aad), aad)
                row.kek_id = current.key_id
            done += len(rows)
        await s.flush()
        return done

    async def kek_usage(self, s: AsyncSession) -> dict[str, int]:
        usage: dict[str, int] = {}
        for model in (DataKey, PlatformKey):
            for kek_id, n in (await s.execute(select(model.kek_id, func.count()).group_by(model.kek_id))).all():
                usage[kek_id] = usage.get(kek_id, 0) + int(n)
        return usage
