# SPDX-License-Identifier: Apache-2.0
"""Inbound events for the matcher's tests: a published workflow's tenant with its inbound keypair (sealed with the
fixture keys the dispatcher reads), an endpoint, bindings, and events recorded through ingress's own function."""

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.crypto import events
from dewpoint.core.ingress.identity import canonical
from dewpoint.core.ingress.keys import PURPOSE
from tests.apps.test_admission import KEYS, OPEN_GRAPH, current, published
from tests.core.ingress.support import record


@dataclass
class Inbound:
    ctx: Any  # the publishing actor's TenantContext
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    workflow_id: uuid.UUID
    endpoint_id: uuid.UUID
    public_key: bytes


async def keypair(owner: Any, tenant_id: uuid.UUID, version: int = 1) -> bytes:
    """The tenant's inbound keypair `version`, its private key sealed with the fixture keys; its public key."""
    private, public = events.generate_keypair()
    sealed = await ClaimCipher(KEYS, purpose=PURPOSE).seal(str(tenant_id), str(version), private)
    async with owner() as s, s.begin():
        await s.execute(
            text(
                "insert into tenant_event_keys (tenant_id, version, public_key, private_sealed) values (:t, :v, :p, :s)"
            ),
            {"t": tenant_id, "v": version, "p": public, "s": sealed},
        )
    return public


async def endpoint(owner: Any, tenant_id: uuid.UUID, user_id: uuid.UUID, **columns: Any) -> uuid.UUID:
    endpoint_id = uuid.uuid4()
    values = {"auth_kind": "bearer", "bearer_digest": b"\x00" * 32, "dedupe_key": b"sealed"} | columns
    names = ", ".join(values)
    async with owner() as s, s.begin():
        await s.execute(
            text(f"insert into webhook_endpoints (id, tenant_id, name, created_by, {names}) "  # noqa: S608
                 f"values (:id, :t, 'hooks', :u, {', '.join(':' + k for k in values)})"),
            {"id": endpoint_id, "t": tenant_id, "u": user_id} | values,
        )  # fmt: skip
    return endpoint_id


async def bind(
    owner: Any, inbound: Inbound, workflow_id: uuid.UUID | None = None, *, filter: list[dict[str, Any]] | None = None,
    enabled: bool = True, endpoint_id: uuid.UUID | None = None,
) -> uuid.UUID:  # fmt: skip
    binding_id = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into trigger_bindings (id, tenant_id, endpoint_id, workflow_id, filter, enabled, created_by) "
                 "values (:id, :t, :e, :w, cast(:f as jsonb), :on, :u)"),
            {"id": binding_id, "t": inbound.tenant_id, "e": endpoint_id or inbound.endpoint_id,
             "w": workflow_id or inbound.workflow_id, "f": _json(filter or []), "on": enabled, "u": inbound.user_id},
        )  # fmt: skip
    return binding_id


def _json(value: object) -> str:
    return canonical(value).decode()


async def inbound(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any, graph: Any = OPEN_GRAPH) -> Inbound:
    """A published workflow (its input any object), the current build recorded, the tenant's keypair, an endpoint."""
    ctx, workflow_id = await published(owner, api, admin, settings, graph)
    await current(dispatch)
    public = await keypair(owner, ctx.tenant_id)
    endpoint_id = await endpoint(owner, ctx.tenant_id, ctx.user.id)
    return Inbound(ctx, ctx.tenant_id, ctx.user.id, workflow_id, endpoint_id, public)


def sealed(inbound: Inbound, event_id: uuid.UUID, payload: object, *, endpoint_id: uuid.UUID | None = None) -> bytes:
    return events.seal(
        inbound.public_key, 1, tenant_id=inbound.tenant_id, endpoint_id=endpoint_id or inbound.endpoint_id,
        event_id=event_id, plaintext=canonical(payload),
    )  # fmt: skip


async def send(ingress: Any, inbound: Inbound, *payloads: object, dedupe: list[bytes | None] | None = None,
               endpoint_id: uuid.UUID | None = None) -> list[uuid.UUID]:  # fmt: skip
    """Events recorded through ingress's function, committed: their ids."""
    ids = [uuid.uuid4() for _ in payloads]
    keys = dedupe or [None] * len(payloads)
    given = [
        (key, None if key is None else hashlib.sha256(canonical(payload)).digest(),
         sealed(inbound, i, payload, endpoint_id=endpoint_id))
        for i, payload, key in zip(ids, payloads, keys, strict=True)
    ]  # fmt: skip
    outcome = await record(ingress, endpoint_id or inbound.endpoint_id, given, ids=ids)
    assert outcome["outcome"] == "recorded", outcome
    return ids


async def event_state(owner: Any, event_id: uuid.UUID) -> dict[str, Any]:
    async with owner() as s:
        found = await s.execute(text("select * from inbound_events where id = :e"), {"e": event_id})
        return dict(found.mappings().one())


async def requests_of(owner: Any, event_id: uuid.UUID) -> list[dict[str, Any]]:
    async with owner() as s:
        found = await s.execute(
            text("select idempotency_key, workflow_id, source, mode, status, reason from run_requests "
                 "where idempotency_key like :k order by idempotency_key"), {"k": f"evt:{event_id}:%"},
        )  # fmt: skip
        return [dict(r) for r in found.mappings()]


async def counters(owner: Any, inbound: Inbound) -> tuple[tuple[int, int], tuple[int, int]]:
    """(the endpoint's pending events and bytes, the tenant's)."""
    endpoint = text("select pending_events, pending_bytes from webhook_endpoints where id = :e")
    tenant = text("select pending_events, pending_bytes from tenant_event_counters where tenant_id = :t")
    async with owner() as s:
        e = (await s.execute(endpoint, {"e": inbound.endpoint_id})).one()
        t = (await s.execute(tenant, {"t": inbound.tenant_id})).one()
    return (e[0], e[1]), (t[0], t[1])


async def lock_waiters(owner: Any) -> int:
    async with owner() as s:
        return int((await s.execute(text("select count(*) from pg_stat_activity where wait_event_type = 'Lock'"))
                    ).scalar_one())  # fmt: skip


async def stored(owner: Any, inbound: Inbound, payload: object) -> uuid.UUID:
    """An event written straight to the table, as ingress would have recorded it, with its counters: for a test whose
    deployment ingress wouldn't record in (a production one)."""
    event_id = uuid.uuid4()
    blob = sealed(inbound, event_id, payload)
    async with owner() as s, s.begin():
        await s.execute(
            text(
                "insert into inbound_events (id, tenant_id, endpoint_id, key_version, sealed, size_bytes) "
                "values (:i, :t, :e, 1, :b, :n)"
            ),
            {"i": event_id, "t": inbound.tenant_id, "e": inbound.endpoint_id, "b": blob, "n": len(blob)},
        )
        await s.execute(
            text(
                "update webhook_endpoints set pending_events = pending_events + 1, pending_bytes = "
                "pending_bytes + :n where id = :e"
            ),
            {"n": len(blob), "e": inbound.endpoint_id},
        )
        await s.execute(
            text(
                "insert into tenant_event_counters (tenant_id, pending_events, pending_bytes) values "
                "(:t, 1, :n) on conflict (tenant_id) do update set pending_events = "
                "tenant_event_counters.pending_events + 1, pending_bytes = "
                "tenant_event_counters.pending_bytes + :n"
            ),
            {"t": inbound.tenant_id, "n": len(blob)},
        )
    return event_id
