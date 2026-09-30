# SPDX-License-Identifier: Apache-2.0
"""Temporal payloads, encrypted with their tenant's data key (engine 2b spec §6.2–6.3).

The tenant comes only from the serialization context: the workflow id Dewpoint built (`engine.runtime.ids`). Without
a context whose workflow id names a tenant, `TenantCodec` refuses to encode or decode: there's no default key, and
a payload's metadata is never trusted to choose one. Every client and worker uses `data_converter`, which also
encrypts failure messages and stack traces (`DefaultFailureConverterWithEncodedAttributes`)."""

import dataclasses
import os
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.api.common.v1 import Payload
from temporalio.converter import (
    ActivitySerializationContext,
    DataConverter,
    DefaultFailureConverterWithEncodedAttributes,
    PayloadCodec,
    SerializationContext,
    WithSerializationContext,
    WorkflowSerializationContext,
)

from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import tenant_scope
from dewpoint.engine.runtime.ids import tenant_of

ENCODING = b"binary/dewpoint-tenant-v1"
TENANT = "dewpoint-tenant"
KEY_VERSION = "dewpoint-key-version"
NONCE_BYTES = 12


class CodecRefusedError(Exception):
    """A payload the codec won't encode or decode. The messages are fixed: they never quote a payload.

    Encoding raises nothing else: whatever stops it (no tenant, a key that can't be read, a database that doesn't
    answer) is this error, with its cause chained. A client encodes before it sends, so when a call fails with it,
    nothing was sent (`apps.runs`)."""


class KeySource(Protocol):
    """A tenant's data keys, by version. Read-only: the codec never creates a key (a tenant gets one when it's
    created)."""

    async def active(self, tenant_id: str) -> tuple[int, AESGCM]: ...

    async def get(self, tenant_id: str, version: int) -> AESGCM: ...


def _aad(tenant_id: str, version: int) -> bytes:
    return f"dewpoint|{tenant_id}|temporal|{version}".encode()  # the keyring's layout: scope, purpose, context


class TenantCodec(PayloadCodec, WithSerializationContext):
    def __init__(self, keys: KeySource, tenant_id: str | None = None) -> None:
        self._keys, self._tenant_id = keys, tenant_id

    def with_context(self, context: SerializationContext) -> "TenantCodec":
        workflow_id = (
            context.workflow_id
            if isinstance(context, WorkflowSerializationContext | ActivitySerializationContext)
            else None
        )
        return TenantCodec(self._keys, tenant_of(workflow_id) if workflow_id else None)

    def _tenant(self) -> str:
        if self._tenant_id is None:
            raise CodecRefusedError("No tenant: the payload's workflow id doesn't name one.")
        return self._tenant_id

    async def encode(self, payloads: Sequence[Payload]) -> list[Payload]:
        tenant = self._tenant()
        try:
            version, key = await self._keys.active(tenant)
            out = []
            for p in payloads:
                nonce = os.urandom(NONCE_BYTES)
                metadata = {"encoding": ENCODING, TENANT: tenant.encode(), KEY_VERSION: str(version).encode()}
                data = nonce + key.encrypt(nonce, p.SerializeToString(), _aad(tenant, version))
                out.append(Payload(metadata=metadata, data=data))
        except Exception as e:
            raise CodecRefusedError(f"The payload couldn't be encrypted ({type(e).__name__}).") from e
        return out

    async def decode(self, payloads: Sequence[Payload]) -> list[Payload]:
        tenant = self._tenant()
        out = []
        for p in payloads:
            if p.metadata.get("encoding") != ENCODING:
                raise CodecRefusedError("A payload that isn't encrypted for a tenant.")
            if p.metadata.get(TENANT) != tenant.encode():
                raise CodecRefusedError("A payload of another tenant than its workflow id names.")
            raw_version = p.metadata.get(KEY_VERSION, b"")
            if not raw_version.isdigit() or len(raw_version) > 9:
                raise CodecRefusedError("A payload without a key version.")
            version = int(raw_version)
            key = await self._keys.get(tenant, version)
            try:
                plain = key.decrypt(p.data[:NONCE_BYTES], p.data[NONCE_BYTES:], _aad(tenant, version))
            except InvalidTag:
                raise CodecRefusedError("A payload that doesn't decrypt under its tenant's key.") from None
            out.append(Payload.FromString(plain))
        return out


def data_converter(keys: KeySource) -> DataConverter:
    """The one converter of every Dewpoint client, worker and replayer."""
    return dataclasses.replace(
        DataConverter.default,
        payload_codec=TenantCodec(keys),
        failure_converter_class=DefaultFailureConverterWithEncodedAttributes,
    )


class KeyringKeys:
    """Tenants' data keys from the keyring, read-only, cached unwrapped in this process and nowhere else: at most
    `size` of them, each for at most `ttl_s` seconds, so a rotation takes effect within `ttl_s`. A missing key is
    never cached: a tenant created after this process started is served at once (spec §6.3)."""

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
        self._cache: OrderedDict[tuple[str, int | None], tuple[float, int, AESGCM]] = OrderedDict()

    async def active(self, tenant_id: str) -> tuple[int, AESGCM]:
        return await self._read(tenant_id, None)

    async def get(self, tenant_id: str, version: int) -> AESGCM:
        return (await self._read(tenant_id, version))[1]

    async def _read(self, tenant_id: str, version: int | None) -> tuple[int, AESGCM]:
        now = self._clock()
        hit = self._cache.get((tenant_id, version))
        if hit is not None and hit[0] > now:
            self._cache.move_to_end((tenant_id, version))
            return hit[1], hit[2]
        tenant = uuid.UUID(tenant_id)
        async with self._sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            found, raw = await self._keyring.read_dek(s, tenant, version)
        entry = (now + self._ttl_s, found, AESGCM(raw))
        for k in {(tenant_id, version), (tenant_id, found)}:
            self._cache[k] = entry
            self._cache.move_to_end(k)
        while len(self._cache) > self._size:
            self._cache.popitem(last=False)
        return found, entry[2]
