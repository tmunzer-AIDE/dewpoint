# SPDX-License-Identifier: Apache-2.0
"""Temporal payloads, encrypted with their tenant's data key (engine 2b spec §6.2–6.3).

The tenant comes only from the serialization context: the workflow id Dewpoint built (`engine.runtime.ids`). Without
a context whose workflow id names a tenant, `TenantCodec` refuses to encode or decode: there's no default key, and
a payload's metadata is never trusted to choose one. Every client and worker uses `data_converter`, which also
encrypts failure messages and stack traces (`DefaultFailureConverterWithEncodedAttributes`).

One exception (the owner's M3 ruling, `apps.tick_contract`): in a `ScheduleTick` workflow's or activity's context,
payloads are written unsealed under `TICK_ENCODING`, and only what the tick contract allows, checked on every write
and every read; a tick's failures are reduced to fixed codes. So no tick holds a payload under a tenant's data key,
and retiring a key never waits for one. A tick's legacy sealed payloads still open, for replay."""

import dataclasses
import os
from collections.abc import Sequence
from typing import Self

from cryptography.exceptions import InvalidTag
from google.protobuf.message import DecodeError
from temporalio.api.common.v1 import Payload
from temporalio.api.failure.v1 import Failure
from temporalio.converter import (
    ActivitySerializationContext,
    DataConverter,
    DefaultFailureConverterWithEncodedAttributes,
    PayloadCodec,
    PayloadConverter,
    SerializationContext,
    WithSerializationContext,
    WorkflowSerializationContext,
)

from dewpoint.apps import tick_contract
from dewpoint.core.crypto.keys import KeyringKeys, KeySource
from dewpoint.engine.runtime.ids import schedule_of, tenant_of

ENCODING = b"binary/dewpoint-tenant-v1"
TICK_ENCODING = b"binary/dewpoint-tick-plain-v1"  # a schedule tick's, unsealed (tick_contract)
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
        tick = _tick(context)
        if tick is not None:
            return TickCodec(self._keys, *tick) if tick else TenantCodec(self._keys)  # another type: neither
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


def _tick(context: SerializationContext) -> tuple[str, str] | tuple[()] | None:
    """A schedule's context: its tenant and schedule when it's a `ScheduleTick` workflow's or activity's, `()` when an
    activity of another type claims a schedule's id; None for any other context."""
    contextual = isinstance(context, WorkflowSerializationContext | ActivitySerializationContext)
    workflow_id = context.workflow_id if contextual else None  # type: ignore[attr-defined]
    named = schedule_of(workflow_id) if workflow_id else None
    if named is None:
        return None
    if isinstance(context, ActivitySerializationContext) and context.workflow_type != tick_contract.WORKFLOW:
        return ()
    return named


class TickCodec(TenantCodec):
    """A `ScheduleTick` execution's payloads (tick_contract): written unsealed under `TICK_ENCODING`, and read back,
    only when the contract allows them for its schedule. A legacy sealed payload opens under its tenant's key."""

    def __init__(self, keys: KeySource, tenant_id: str, schedule_id: str) -> None:
        super().__init__(keys, tenant_id)
        self._schedule_id = schedule_id

    async def encode(self, payloads: Sequence[Payload]) -> list[Payload]:
        tenant = self._tenant()
        out = []
        for p in payloads:
            if not tick_contract.allowed(p, self._schedule_id):
                raise CodecRefusedError("A tick's payload outside its contract.")
            marked = {"encoding": TICK_ENCODING, TENANT: tenant.encode()}
            out.append(Payload(metadata=marked, data=p.SerializeToString()))
        return out

    async def decode(self, payloads: Sequence[Payload]) -> list[Payload]:
        tenant = self._tenant()
        out = []
        for p in payloads:
            if p.metadata.get("encoding") != TICK_ENCODING:
                out.extend(await super().decode([p]))  # legacy: sealed before the exception
                continue
            if p.metadata.get(TENANT) != tenant.encode():
                raise CodecRefusedError("A payload of another tenant than its workflow id names.")
            try:
                inner = Payload.FromString(p.data)
            except DecodeError:
                raise CodecRefusedError("A tick's payload that isn't one.") from None
            if not tick_contract.allowed(inner, self._schedule_id):
                raise CodecRefusedError("A tick's payload outside its contract.")
            out.append(inner)
        return out


def _reduce(failure: Failure) -> None:
    """A tick's failure, and its causes', reduced to a code of the contract: no text, details or stack trace."""
    info = failure.application_failure_info if failure.HasField("application_failure_info") else None
    code = info.type if info is not None and info.type in tick_contract.FAILURES else tick_contract.FAILED
    failure.message, failure.stack_trace = code, ""
    failure.ClearField("encoded_attributes")
    if info is not None:
        info.type = code
        info.ClearField("details")
    for kind, carried in (("canceled_failure_info", "details"), ("timeout_failure_info", "last_heartbeat_details"),
                          ("reset_workflow_failure_info", "last_heartbeat_details")):  # fmt: skip
        if failure.HasField(kind):  # type: ignore[arg-type]
            getattr(failure, kind).ClearField(carried)
    if failure.HasField("cause"):
        _reduce(failure.cause)


class FailureConverter(DefaultFailureConverterWithEncodedAttributes, WithSerializationContext):
    """Failure messages and stack traces encrypted (as payloads, by the codec); in a `ScheduleTick` execution's
    context, each failure reduced to a code of the tick contract instead, nothing encoded."""

    def __init__(self, *, tick: bool = False) -> None:
        super().__init__()
        self._tick = tick
        if tick:
            self._encode_common_attributes = False

    def with_context(self, context: SerializationContext) -> Self:
        return type(self)(tick=True) if _tick(context) else self

    def to_failure(self, exception: BaseException, payload_converter: PayloadConverter, failure: Failure) -> None:
        super().to_failure(exception, payload_converter, failure)
        if self._tick:
            _reduce(failure)


def data_converter(keys: KeySource) -> DataConverter:
    """The one converter of every Dewpoint client, worker and replayer."""
    return dataclasses.replace(
        DataConverter.default,
        payload_codec=TenantCodec(keys),
        failure_converter_class=FailureConverter,
    )


__all__ = ["CodecRefusedError", "KeySource", "KeyringKeys", "TenantCodec", "TickCodec", "data_converter"]
