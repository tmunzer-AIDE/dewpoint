# SPDX-License-Identifier: Apache-2.0
"""`TenantCodec` (engine 2b spec §6.2, §12 "codec fail-closed"): a payload is encrypted with the key of the tenant its
workflow id names, and nothing else chooses the key."""

import uuid

import pytest
from temporalio.api.common.v1 import Payload
from temporalio.converter import (
    ActivitySerializationContext,
    DataConverter,
    WorkflowSerializationContext,
)

from dewpoint.apps.codec import (
    ENCODING,
    KEY_VERSION,
    TENANT,
    CodecRefusedError,
    TenantCodec,
)
from dewpoint.core.crypto.keyring import NoKeyError
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.size import CODEC_OVERHEAD
from tests.support.keys import FixtureKeys

A, B = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
RUN = str(uuid.UUID(int=3))


def workflow(tenant_id: str, suffix: str = "") -> WorkflowSerializationContext:
    return WorkflowSerializationContext(namespace="default", workflow_id=run_workflow_id(tenant_id, RUN) + suffix)


def activity(workflow_id: str | None) -> ActivitySerializationContext:
    return ActivitySerializationContext(
        namespace="default",
        activity_id="1",
        activity_type="dewpoint.project",
        activity_task_queue="dewpoint-engine",
        workflow_id=workflow_id,
        workflow_type="RunGraph",
        is_local=False,
    )


def payload(value: object) -> Payload:
    [p] = DataConverter.default.payload_converter.to_payloads([value])
    return p


def codec(keys: FixtureKeys | None = None) -> TenantCodec:
    return TenantCodec(keys or FixtureKeys())


async def test_a_payload_round_trips_under_its_tenants_key() -> None:
    plain = payload({"tenant_id": A, "x": "secret"})
    for context in (workflow(A), workflow(A, f"/{uuid.UUID(int=5)}/l:0/batch:0"), activity(run_workflow_id(A, RUN))):
        c = codec().with_context(context)
        [sealed] = await c.encode([plain])
        assert sealed.metadata["encoding"] == ENCODING
        assert (sealed.metadata[TENANT], sealed.metadata[KEY_VERSION]) == (A.encode(), b"1")
        assert b"secret" not in sealed.SerializeToString()
        assert await c.decode([sealed]) == [plain]


@pytest.mark.parametrize(
    "context",
    [
        None,
        WorkflowSerializationContext(namespace="default", workflow_id=RUN),  # an id from before 2b-1a
        WorkflowSerializationContext(namespace="default", workflow_id=f"t:{A}:run:{RUN}\n"),
        activity(None),  # an activity no workflow started
    ],
)
async def test_without_a_tenant_it_refuses_both_ways(context: WorkflowSerializationContext | None) -> None:
    sealed = (await codec().with_context(workflow(A)).encode([payload(1)]))[0]
    c = codec() if context is None else codec().with_context(context)
    with pytest.raises(CodecRefusedError, match="No tenant"):
        await c.encode([payload(1)])
    with pytest.raises(CodecRefusedError, match="No tenant"):
        await c.decode([sealed])


async def test_another_tenants_payload_is_refused_whatever_its_metadata_says() -> None:
    [sealed] = await codec().with_context(workflow(A)).encode([payload(1)])
    with pytest.raises(CodecRefusedError, match="another tenant"):
        await codec().with_context(workflow(B)).decode([sealed])
    relabeled = Payload(metadata={**sealed.metadata, TENANT: B.encode()}, data=sealed.data)
    with pytest.raises(CodecRefusedError, match="doesn't decrypt"):  # the tenant is bound into the associated data
        await codec().with_context(workflow(B)).decode([relabeled])


async def test_a_plaintext_or_tampered_payload_is_refused() -> None:
    c = codec().with_context(workflow(A))
    with pytest.raises(CodecRefusedError, match="isn't encrypted"):
        await c.decode([payload(1)])
    [sealed] = await c.encode([payload(1)])
    flipped = Payload(metadata=dict(sealed.metadata), data=sealed.data[:-1] + bytes([sealed.data[-1] ^ 1]))
    with pytest.raises(CodecRefusedError, match="doesn't decrypt"):
        await c.decode([flipped])
    for version in (b"", b"x", b"2"):  # no version, a garbled one, another (its key doesn't open it)
        other = Payload(metadata={**sealed.metadata, KEY_VERSION: version}, data=sealed.data)
        with pytest.raises(CodecRefusedError):
            await c.decode([other])


async def test_after_a_rotation_older_payloads_still_decode() -> None:
    [old] = await codec(FixtureKeys(version=1)).with_context(workflow(A)).encode([payload("before")])
    rotated = codec(FixtureKeys(version=2)).with_context(workflow(A))
    [new] = await rotated.encode([payload("after")])
    assert (old.metadata[KEY_VERSION], new.metadata[KEY_VERSION]) == (b"1", b"2")
    assert await rotated.decode([old, new]) == [payload("before"), payload("after")]


async def test_a_tenant_without_a_key_is_refused() -> None:
    """Every failure to encode is the codec's refusal, so a client that sends what it encodes knows nothing was sent
    (owner's review, Task 6); the cause stays chained."""
    c = codec(FixtureKeys(missing={A})).with_context(workflow(A))
    with pytest.raises(CodecRefusedError, match=r"couldn't be encrypted \(NoKeyError\)") as e:
        await c.encode([payload(1)])
    assert isinstance(e.value.__cause__, NoKeyError)


@pytest.mark.parametrize("size", [0, 1, 1_000, 65_536, 1_835_008, 2_097_152])
async def test_the_overhead_bound_covers_every_size(size: int) -> None:
    """Spec §5.2: the guard adds CODEC_OVERHEAD to a payload's JSON bytes; Temporal measures the encoded payload."""
    plain = payload("x" * size)  # the guard measures the JSON with the SDK's own converter, as this does
    [sealed] = await codec(FixtureKeys(version=999_999_999)).with_context(workflow(A)).encode([plain])
    assert sealed.ByteSize() <= len(plain.data) + CODEC_OVERHEAD
