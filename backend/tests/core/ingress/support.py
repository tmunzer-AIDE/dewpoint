# SPDX-License-Identifier: Apache-2.0
"""Ingress's tables in a test: a tenant with its inbound keypair, an endpoint, and calls to the recording function as
the ingress login."""

import hashlib
import os
import uuid
from typing import Any

from sqlalchemy import text

from dewpoint.core.auth.users import create_user
from dewpoint.core.crypto.kek import Kek, KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.ingress.keys import ensure_event_key

KEYRING = Keyring(KekSet(Kek("k1", os.urandom(32))))
RECORD = text(
    "select record_inbound_events(:e, :refusal, :read, cast(:ids as uuid[]), cast(:sealed as bytea[]), "
    "cast(:versions as integer[]), cast(:dedupe as bytea[]), cast(:digests as bytea[]))"
)


async def endpoint(owner: Any, **columns: Any) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant (with its keypair) and one of its endpoints, a bearer one unless `columns` say otherwise."""
    tenant, endpoint_id = uuid.uuid4(), uuid.uuid4()
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


async def record(
    ingress: Any, endpoint_id: uuid.UUID, events: list[tuple[bytes | None, bytes | None, bytes]] | None = None, *,
    refusal: str | None = None, read: int = 0, versions: list[int] | None = None, ids: list[uuid.UUID] | None = None,
) -> dict[str, Any]:  # fmt: skip
    """The recording function's outcome for `events`, each (dedupe key, content digest, sealed bytes), committed."""
    given = events or []
    params = {
        "e": endpoint_id, "refusal": refusal, "read": read,
        "ids": ids if ids is not None else [uuid.uuid4() for _ in given],
        "sealed": [sealed for _, _, sealed in given], "versions": versions or [1] * len(given),
        "dedupe": [dedupe for dedupe, _, _ in given], "digests": [d for _, d, _ in given],
    }  # fmt: skip
    async with ingress() as s, s.begin():
        return dict((await s.execute(RECORD, params)).scalar_one())


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
