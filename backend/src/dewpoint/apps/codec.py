# SPDX-License-Identifier: Apache-2.0
"""Temporal payloads, encrypted with their tenant's data key (engine 2b spec §6.2–6.3).

The tenant comes only from the serialization context: the workflow id Dewpoint built (`engine.runtime.ids`). Without
a context whose workflow id names a tenant, `TenantCodec` refuses to encode or decode: there's no default key, and
a payload's metadata is never trusted to choose one. Every client and worker uses `data_converter`, which also
encrypts failure messages and stack traces (`DefaultFailureConverterWithEncodedAttributes`)."""

import dataclasses
import os
from collections.abc import Sequence

from cryptography.exceptions import InvalidTag
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

from dewpoint.core.crypto.keys import KeyringKeys, KeySource
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


__all__ = ["CodecRefusedError", "KeySource", "KeyringKeys", "TenantCodec", "data_converter"]
