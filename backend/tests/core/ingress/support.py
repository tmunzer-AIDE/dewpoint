# SPDX-License-Identifier: Apache-2.0
"""Ingress's tables in a test: a tenant with its inbound keypair, an endpoint, and calls to the recording function as
the ingress login."""

import hashlib
import os
import struct
import uuid
from typing import Any

from sqlalchemy import text

from dewpoint.core.auth.users import create_user
from dewpoint.core.crypto import events
from dewpoint.core.crypto.kek import Kek, KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.ingress.keys import ensure_event_key

KEYRING = Keyring(KekSet(Kek("k1", os.urandom(32))))
RECORD = text(
    "select record_inbound_events(:e, :refusal, :read, cast(:ids as uuid[]), cast(:sealed as bytea[]), "
    "cast(:versions as integer[]), cast(:dedupe as bytea[]), cast(:digests as bytea[]))"
)


async def endpoint(owner: Any, endpoint_id: uuid.UUID | None = None, **columns: Any) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant (with its keypair) and one of its endpoints, a bearer one unless `columns` say otherwise."""
    tenant, endpoint_id = uuid.uuid4(), endpoint_id or uuid.uuid4()
    async with owner() as s, s.begin():
        user = (await create_user(s, email=f"{tenant.hex[:10]}@corp.test", password="violet-otter-canyon-42")).id
        await s.execute(text("insert into tenants(id,name,slug) values (:t,'T',:s)"), {"t": tenant, "s": tenant.hex})
        await ensure_event_key(s, KEYRING, tenant)
        values = {"auth_kind": "bearer", "bearer_digest": hashlib.sha256(b"token").digest(),
                  "dedupe_key": b"sealed-dedupe-key"} | columns  # fmt: skip
        names = ", ".join(values)
        await s.execute(
            text(f"insert into webhook_endpoints (id, tenant_id, name, created_by, {names}) "  # noqa: S608
                 f"values (:id, :t, 'hooks', :u, {', '.join(':' + k for k in values)})"),
            {"id": endpoint_id, "t": tenant, "u": user} | values,
        )  # fmt: skip
    return tenant, endpoint_id


def key(n: int) -> bytes:
    return hashlib.sha256(f"key-{n}".encode()).digest()


def digest(n: int) -> bytes:
    return hashlib.sha256(f"digest-{n}".encode()).digest()


def sealed_layout(blob: bytes, version: int) -> bytes:
    """A test's stand-in for a sealed event, in the sealed layout (its format byte, its keypair version, at least the
    sealing's overhead), `blob`'s own bytes after the header: as long as `blob` once it reaches the overhead. Never a
    real ciphertext: what the recording function checks is the layout, the dispatcher opening it. A real sealed
    event of `version` is left as it is."""
    body = blob[5:] if len(blob) >= events.OVERHEAD else blob.rjust(events.OVERHEAD - 5, b"\0")
    return b"\x01" + struct.pack(">I", version) + body


def record_params(
    endpoint_id: uuid.UUID, given: list[tuple[bytes | None, bytes | None, bytes]] | None = None, *,
    refusal: str | None = None, read: int = 0, versions: list[int] | None = None, ids: list[uuid.UUID] | None = None,
    layout: bool = True,
) -> dict[str, Any]:  # fmt: skip
    """RECORD's parameters for `given` events, each (dedupe key, content digest, sealed bytes), each sealed bytes put
    in the sealed layout (`sealed_layout`) unless `layout` is False."""
    given = given or []
    versions = versions or [1] * len(given)
    named = versions + [1] * (len(given) - len(versions))  # arrays that don't line up are the function's to refuse
    sealed = [sealed_layout(blob, v) if layout else blob for (_, _, blob), v in zip(given, named, strict=False)]
    return {
        "e": endpoint_id, "refusal": refusal, "read": read,
        "ids": ids if ids is not None else [uuid.uuid4() for _ in given],
        "sealed": sealed, "versions": versions,
        "dedupe": [dedupe for dedupe, _, _ in given], "digests": [d for _, d, _ in given],
    }  # fmt: skip


async def record(
    ingress: Any, endpoint_id: uuid.UUID, given: list[tuple[bytes | None, bytes | None, bytes]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:  # fmt: skip
    """The recording function's outcome for `given` events (`record_params`), committed."""
    async with ingress() as s, s.begin():
        return dict((await s.execute(RECORD, record_params(endpoint_id, given, **kwargs))).scalar_one())


async def state(owner: Any, endpoint_id: uuid.UUID) -> dict[str, Any]:
    async with owner() as s:
        row = (await s.execute(text("select * from webhook_endpoints where id = :e"), {"e": endpoint_id})).mappings()
        return dict(row.one())


async def tenant_state(owner: Any, tenant: uuid.UUID) -> dict[str, Any]:
    async with owner() as s:
        found = await s.execute(text("select * from tenant_event_counters where tenant_id = :t"), {"t": tenant})
        return dict(found.mappings().one())


async def events_of(owner: Any, endpoint_id: uuid.UUID) -> list[dict[str, Any]]:
    async with owner() as s:
        found = await s.execute(text("select * from inbound_events where endpoint_id = :e order by received_at, id"),
                                {"e": endpoint_id})  # fmt: skip
        return [dict(r) for r in found.mappings()]
