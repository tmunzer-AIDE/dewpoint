# SPDX-License-Identifier: Apache-2.0
"""Webhook endpoints, bindings and inbound events, as the API writes and reads them (engine 2b spec §8.3; the owner's
ruling 10 on the 2b-3b outline).

An endpoint's secret is made by Dewpoint and shown once, when it's made or rotated: a bearer token, kept as its SHA-256
digest, or an HMAC secret, sealed under the ingress key with the endpoint's id as its context (ingress opens it so).
Its dedupe-digest key is sealed the same way and never changes, so rotating the secret keeps deduplication. Making an
endpoint makes the tenant's inbound keypair if it has none. Its identity (how it authenticates, where its ids are) is
fixed once it's made; its byte burst always covers the largest charge it permits.

A binding names a workflow of the endpoint's tenant, at most once per endpoint and at most `MAX_BINDINGS` per endpoint
(counted under the endpoint's row lock), with a filter checked when written. An admin cancels a pending or dead event,
or an endpoint's pending events, under the lock order (the tenant's lifecycle lock shared, the endpoint's row, the
tenant's counter row, the events), releasing what was pending; every write is audited."""

import ipaddress
import re
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit import service as audit
from dewpoint.core.crypto.ingress import (
    DEDUPE_KEY,
    HMAC_SECRET,
    IngressKey,
    bearer_digest,
    new_bearer_token,
    new_dedupe_key,
    new_hmac_secret,
)
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.ingress.counters import lock_tenant_shared, release
from dewpoint.core.ingress.filters import MAX_BINDINGS, FilterError, validated
from dewpoint.core.ingress.keys import ensure_event_key
from dewpoint.core.models.ingress import InboundEvent, TenantEventCounters, TriggerBinding, WebhookEndpoint
from dewpoint.core.models.workflows import Workflow
from dewpoint.core.retention.cutoff import Cutoff, cutoff, event_kept, kept

MIB = 1024 * 1024
MAX_BODY = 5 * MIB  # the largest body limit, and ingress's global cap
DEFAULT_BYTE_BURST = 10 * MIB
SIGNATURE_HEADER, TIMESTAMP_HEADER = "x-dewpoint-signature", "x-dewpoint-timestamp"
HEADER = re.compile(r"[!#$%&'*+.^_`|~0-9a-z-]{1,64}")  # an HTTP token, lower case
# Headers a sender can't be asked to put an id or a signature in: the transport's, or what a proxy rewrites.
RESERVED_HEADERS = frozenset({
    "authorization", "connection", "content-length", "content-type", "cookie", "forwarded", "host",
    "transfer-encoding", "x-forwarded-for", "x-forwarded-proto", "x-real-ip",
})  # fmt: skip
MAX_POINTER = 256
MAX_ALLOWLIST = 32
LISTED = 100  # events a listing shows at most
CANCELLED = "cancelled"
UPDATABLE = frozenset({"name", "enabled", "allowlist", "tolerance_s", "body_limit", "signature_header",
                       "timestamp_header"})  # fmt: skip


class WebhookRefusedError(Exception):
    """A write the API refuses: the HTTP status and the fixed detail to answer with."""

    def __init__(self, status: int, detail: dict[str, Any]) -> None:
        super().__init__(detail["error"])
        self.status, self.detail = status, detail


def byte_burst(body_limit: int) -> int:
    """A byte burst that covers the largest charge an endpoint permits: its largest sealed batch, and the largest body
    ingress reads before it authenticates (the schema's `webhook_endpoints_bursts`)."""
    return max(DEFAULT_BYTE_BURST, 5 * body_limit + 128 * 500, MAX_BODY)


def _header_ok(name: object) -> bool:
    return isinstance(name, str) and bool(HEADER.fullmatch(name)) and name not in RESERVED_HEADERS


def _networks(given: object) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None:
    """An allowlist's networks, or None when it isn't one: strict, a host's bits never set past its prefix."""
    if not isinstance(given, list) or len(given) > MAX_ALLOWLIST or not all(isinstance(e, str) for e in given):
        return None
    try:
        return [ipaddress.ip_network(entry) for entry in given]
    except ValueError:
        return None


def _id_problems(given: Mapping[str, Any], id_source: str) -> list[str]:
    """Where a new endpoint's ids are, when that isn't valid."""
    problems = []
    if id_source == "pointer":
        pointer = given.get("id_pointer")
        if not (isinstance(pointer, str) and pointer.startswith("/") and len(pointer) <= MAX_POINTER):
            problems.append("id_pointer")
    elif given.get("id_pointer") is not None:
        problems.append("id_pointer")
    if id_source == "header":
        if not _header_ok(given.get("id_header")):
            problems.append("id_header")
    elif given.get("id_header") is not None:
        problems.append("id_header")
    return problems


def _problems(given: Mapping[str, Any], *, auth: str, id_source: str | None) -> list[str]:
    """The fields of an endpoint that aren't valid: a pointer that isn't one, a header a sender can't use, an
    allowlist entry that isn't a network, a field its kind doesn't take. Where its ids are is checked only when it's
    made (`id_source`): an update never writes it."""
    problems = [] if id_source is None else _id_problems(given, id_source)
    events_pointer = given.get("events_pointer")
    if events_pointer is not None and not (
        isinstance(events_pointer, str) and (events_pointer == "" or events_pointer.startswith("/"))
        and len(events_pointer) <= MAX_POINTER
    ):  # fmt: skip
        problems.append("events_pointer")
    for field in ("signature_header", "timestamp_header"):
        value = given.get(field)
        if value is not None and (auth != "hmac" or not _header_ok(value)):
            problems.append(field)
    if "allowlist" in given and _networks(given["allowlist"]) is None:
        problems.append("allowlist")
    return problems


def _secret(key: IngressKey, endpoint_id: uuid.UUID, auth: str) -> tuple[str, dict[str, bytes | None]]:
    """A new secret for the endpoint, and what's stored of it."""
    if auth == "bearer":
        token = new_bearer_token()
        return token, {"bearer_digest": bearer_digest(token), "hmac_secret": None}
    secret = new_hmac_secret()
    return secret, {"bearer_digest": None, "hmac_secret": key.seal(HMAC_SECRET, str(endpoint_id), secret.encode())}


async def _audit(s: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None, action: str, target_type: str,
                 target_id: uuid.UUID, details: dict[str, object]) -> None:  # fmt: skip
    await audit.record(s, tenant_id=tenant_id, actor_id=actor_id, action=action, target_type=target_type,
                       target_id=str(target_id), details=details)  # fmt: skip


async def create_endpoint(
    s: AsyncSession, keyring: Keyring, key: IngressKey, *, tenant_id: uuid.UUID, actor_id: uuid.UUID,
    given: Mapping[str, Any],
) -> tuple[WebhookEndpoint, str]:  # fmt: skip
    """The endpoint and its secret, to show once. Raises WebhookRefusedError."""
    auth, id_source = given["auth"], given["id_source"]
    problems = _problems(given, auth=auth, id_source=id_source)
    if problems:
        raise WebhookRefusedError(422, {"error": "endpoint_invalid", "fields": problems})
    await ensure_event_key(s, keyring, tenant_id)
    endpoint_id = uuid.uuid4()
    secret, stored = _secret(key, endpoint_id, auth)
    burst = byte_burst(given["body_limit"])
    endpoint = WebhookEndpoint(
        id=endpoint_id, tenant_id=tenant_id, name=given["name"], enabled=given["enabled"], auth_kind=auth, **stored,
        signature_header=(given.get("signature_header") or SIGNATURE_HEADER) if auth == "hmac" else None,
        timestamp_header=(given.get("timestamp_header") or TIMESTAMP_HEADER) if auth == "hmac" else None,
        tolerance_s=given["tolerance_s"], allowlist=_networks(given.get("allowlist") or []),
        body_limit=given["body_limit"], id_source=id_source, id_pointer=given.get("id_pointer"),
        id_header=given.get("id_header"), events_pointer=given.get("events_pointer"),
        dedupe_key=key.seal(DEDUPE_KEY, str(endpoint_id), new_dedupe_key()), byte_burst=burst, byte_tokens=burst,
        created_by=actor_id,
    )  # fmt: skip
    s.add(endpoint)
    await s.flush()
    await s.refresh(endpoint)  # the defaults the database set, read now (never lazily)
    await _audit(s, tenant_id, actor_id, "webhook_endpoint.create", "webhook_endpoint", endpoint_id,
                 {"name": endpoint.name, "auth": auth, "id_source": id_source})  # fmt: skip
    return endpoint, secret


async def found_endpoint(s: AsyncSession, endpoint_id: uuid.UUID, *, lock: bool = False) -> WebhookEndpoint:
    """The caller's tenant's endpoint (row-level security), locked when asked. Raises WebhookRefusedError."""
    query = select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id).execution_options(populate_existing=True)
    endpoint = (await s.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if endpoint is None:
        raise WebhookRefusedError(404, {"error": "not_found"})
    return endpoint


async def rotate_secret(s: AsyncSession, key: IngressKey, *, endpoint: WebhookEndpoint, actor_id: uuid.UUID) -> str:
    """A new secret, to show once; the dedupe-digest key kept."""
    secret, stored = _secret(key, endpoint.id, endpoint.auth_kind)
    endpoint.bearer_digest, endpoint.hmac_secret = stored["bearer_digest"], stored["hmac_secret"]
    endpoint.updated_at = func.now()
    await s.flush()
    await _audit(s, endpoint.tenant_id, actor_id, "webhook_endpoint.rotate_secret", "webhook_endpoint", endpoint.id,
                 {"auth": endpoint.auth_kind})  # fmt: skip
    return secret


async def update_endpoint(
    s: AsyncSession, *, endpoint: WebhookEndpoint, actor_id: uuid.UUID, changes: Mapping[str, Any]
) -> WebhookEndpoint:
    """Only what `UPDATABLE` names changes; an endpoint's identity (how it authenticates, where its events and their
    ids are) never does. Raises WebhookRefusedError."""
    fixed = sorted(set(changes) - UPDATABLE)
    nulled = sorted(k for k in changes if changes[k] is None)
    problems = fixed + nulled + _problems(changes, auth=endpoint.auth_kind, id_source=None)
    if problems:
        raise WebhookRefusedError(422, {"error": "endpoint_invalid", "fields": sorted(set(problems))})
    for field, value in changes.items():
        setattr(endpoint, field, _networks(value) if field == "allowlist" else value)
    if "body_limit" in changes:
        endpoint.byte_burst = max(endpoint.byte_burst, byte_burst(changes["body_limit"]))
    endpoint.updated_at = func.now()
    await s.flush()
    await s.refresh(endpoint)
    await _audit(s, endpoint.tenant_id, actor_id, "webhook_endpoint.update", "webhook_endpoint", endpoint.id,
                 {"fields": sorted(changes)})  # fmt: skip
    return endpoint


async def create_binding(
    s: AsyncSession, *, endpoint_id: uuid.UUID, actor_id: uuid.UUID, workflow_id: uuid.UUID, filter: object,
    enabled: bool,
) -> TriggerBinding:  # fmt: skip
    try:
        clauses = validated(filter)
    except FilterError as e:
        raise WebhookRefusedError(422, {"error": "filter_invalid", "message": str(e)}) from None
    endpoint = await found_endpoint(s, endpoint_id, lock=True)  # serializes the cap's count
    if await s.get(Workflow, workflow_id) is None:  # row-level security: the endpoint's tenant's only
        raise WebhookRefusedError(404, {"error": "workflow_not_found"})
    bound = (await s.execute(select(TriggerBinding.workflow_id).where(TriggerBinding.endpoint_id == endpoint.id))
             ).scalars().all()  # fmt: skip
    if workflow_id in bound:
        raise WebhookRefusedError(409, {"error": "binding_exists"})
    if len(bound) >= MAX_BINDINGS:
        raise WebhookRefusedError(409, {"error": "binding_cap", "max": MAX_BINDINGS})
    binding = TriggerBinding(id=uuid.uuid4(), tenant_id=endpoint.tenant_id, endpoint_id=endpoint.id,
                             workflow_id=workflow_id, filter=clauses, enabled=enabled, created_by=actor_id)  # fmt: skip
    s.add(binding)
    await s.flush()
    await _audit(s, endpoint.tenant_id, actor_id, "webhook_binding.create", "webhook_binding", binding.id,
                 {"endpoint_id": str(endpoint.id), "workflow_id": str(workflow_id)})  # fmt: skip
    return binding


async def found_binding(s: AsyncSession, binding_id: uuid.UUID) -> TriggerBinding:
    binding = await s.get(TriggerBinding, binding_id, populate_existing=True)
    if binding is None:
        raise WebhookRefusedError(404, {"error": "not_found"})
    return binding


async def update_binding(
    s: AsyncSession, *, binding: TriggerBinding, actor_id: uuid.UUID, changes: Mapping[str, Any]
) -> TriggerBinding:
    if "filter" in changes:
        try:
            binding.filter = validated(changes["filter"])
        except FilterError as e:
            raise WebhookRefusedError(422, {"error": "filter_invalid", "message": str(e)}) from None
    if "enabled" in changes:
        binding.enabled = changes["enabled"]
    await s.flush()
    await _audit(s, binding.tenant_id, actor_id, "webhook_binding.update", "webhook_binding", binding.id,
                 {"fields": sorted(changes)})  # fmt: skip
    return binding


async def delete_binding(s: AsyncSession, *, binding: TriggerBinding, actor_id: uuid.UUID) -> None:
    await s.delete(binding)
    await s.flush()
    await _audit(s, binding.tenant_id, actor_id, "webhook_binding.delete", "webhook_binding", binding.id,
                 {"endpoint_id": str(binding.endpoint_id), "workflow_id": str(binding.workflow_id)})  # fmt: skip


async def events_of(s: AsyncSession, endpoint_id: uuid.UUID, status: str | None, *, dead: bool,
                    kept_after: Cutoff) -> list[InboundEvent]:  # fmt: skip
    """The endpoint's newest events; dead ones only when `dead` (the caller has `tenant.manage`: the owner's M3
    review), filtered by status or not; none past the retention cutoff `kept_after` (§10.1)."""
    query = select(InboundEvent).where(InboundEvent.endpoint_id == endpoint_id, kept(InboundEvent.ended_at, kept_after))
    if status is not None:
        query = query.where(InboundEvent.status == status)
    if not dead:
        query = query.where(InboundEvent.status != "dead")
    order = (InboundEvent.received_at.desc(), InboundEvent.id.desc())
    return list((await s.execute(query.order_by(*order).limit(LISTED))).scalars())


async def dead_events(s: AsyncSession, *, kept_after: Cutoff) -> list[InboundEvent]:
    query = select(InboundEvent).where(InboundEvent.status == "dead", kept(InboundEvent.ended_at, kept_after))
    return list((await s.execute(query.order_by(InboundEvent.ended_at.desc()).limit(LISTED))).scalars())


async def _locked(s: AsyncSession, tenant_id: uuid.UUID, endpoint_id: uuid.UUID) -> None:
    """The lock order's first steps for a cancel: the tenant's lifecycle lock shared, the endpoint's row, the
    tenant's counter row."""
    await lock_tenant_shared(s, tenant_id)
    await found_endpoint(s, endpoint_id, lock=True)
    await s.execute(select(TenantEventCounters.tenant_id).where(TenantEventCounters.tenant_id == tenant_id)
                    .with_for_update())  # fmt: skip


async def cancel_event(s: AsyncSession, *, tenant_id: uuid.UUID, event_id: uuid.UUID,
                       actor_id: uuid.UUID) -> InboundEvent:  # fmt: skip
    """A pending or dead event cancelled; what was pending released. One past the retention cutoff isn't found
    (§10.1). Raises WebhookRefusedError."""
    seen = await s.get(InboundEvent, event_id)
    if seen is None or not await event_kept(s, await cutoff(s, tenant_id), seen):
        raise WebhookRefusedError(404, {"error": "not_found"})
    await _locked(s, tenant_id, seen.endpoint_id)
    event = (await s.execute(select(InboundEvent).where(InboundEvent.id == event_id).with_for_update()
                             .execution_options(populate_existing=True))).scalar_one()  # fmt: skip
    if event.status not in ("pending", "dead"):
        raise WebhookRefusedError(409, {"error": "not_cancellable", "status": event.status})
    was = event.status
    if was == "pending":
        await release(s, tenant_id, event.endpoint_id, event.size_bytes)
        event.ended_at = func.now()
    event.status, event.reason = CANCELLED, CANCELLED
    await s.flush()
    await s.refresh(event)
    await _audit(s, tenant_id, actor_id, "inbound_event.cancel", "inbound_event", event.id,
                 {"endpoint_id": str(event.endpoint_id), "was": was})  # fmt: skip
    return event


async def cancel_pending(s: AsyncSession, *, tenant_id: uuid.UUID, endpoint_id: uuid.UUID,
                         actor_id: uuid.UUID) -> int:  # fmt: skip
    """Every pending event of the endpoint cancelled at once, its counters released: how many."""
    await _locked(s, tenant_id, endpoint_id)
    events = (
        await s.execute(
            select(InboundEvent).where(InboundEvent.endpoint_id == endpoint_id, InboundEvent.status == "pending")
            .order_by(InboundEvent.id).with_for_update().execution_options(populate_existing=True)
        )
    ).scalars().all()  # fmt: skip
    for event in events:
        event.status, event.reason, event.ended_at = CANCELLED, CANCELLED, func.now()
    if events:
        await release(s, tenant_id, endpoint_id, sum(e.size_bytes for e in events), events_n=len(events))
    await s.flush()
    await _audit(s, tenant_id, actor_id, "webhook_endpoint.cancel_pending", "webhook_endpoint", endpoint_id,
                 {"cancelled": len(events)})  # fmt: skip
    return len(events)


async def usage(s: AsyncSession, tenant_id: uuid.UUID) -> dict[str, int]:
    """The tenant's pending backlog and retained storage, against their quotas."""
    counters = await s.get(TenantEventCounters, tenant_id, populate_existing=True)
    fields = ("pending_events", "pending_bytes", "retained_events", "retained_bytes")
    quotas = {"pending_events_max": 50_000, "pending_bytes_max": 256 * MIB, "retained_events_max": 250_000,
              "retained_bytes_max": 1024 * MIB}  # the schema's defaults, before the tenant's first event  # fmt: skip
    if counters is None:
        return dict.fromkeys(fields, 0) | quotas
    return {f: getattr(counters, f) for f in (*fields, *quotas)}


def endpoint_body(endpoint: WebhookEndpoint) -> dict[str, object]:
    """An endpoint as the API shows it: never its secret, its digest or its dedupe key."""
    return {
        "id": str(endpoint.id), "name": endpoint.name, "enabled": endpoint.enabled, "auth": endpoint.auth_kind,
        "signature_header": endpoint.signature_header, "timestamp_header": endpoint.timestamp_header,
        "tolerance_s": endpoint.tolerance_s, "allowlist": [str(n) for n in endpoint.allowlist or []],
        "body_limit": endpoint.body_limit, "id_source": endpoint.id_source, "id_pointer": endpoint.id_pointer,
        "id_header": endpoint.id_header, "events_pointer": endpoint.events_pointer, "path": f"/hooks/{endpoint.id}",
        "pending_events": endpoint.pending_events, "pending_bytes": endpoint.pending_bytes,
        "retained_events": endpoint.retained_events, "retained_bytes": endpoint.retained_bytes,
        "created_at": endpoint.created_at.isoformat() if endpoint.created_at else None,
    }  # fmt: skip


def binding_body(binding: TriggerBinding) -> dict[str, object]:
    return {"id": str(binding.id), "endpoint_id": str(binding.endpoint_id), "workflow_id": str(binding.workflow_id),
            "filter": binding.filter, "enabled": binding.enabled}  # fmt: skip


def event_body(event: InboundEvent) -> dict[str, object]:
    """An event's metadata: never its payload, its dedupe key or its digest."""

    def when(value: Any) -> str | None:
        return value.isoformat() if value is not None else None

    return {
        "id": str(event.id), "endpoint_id": str(event.endpoint_id), "status": event.status, "reason": event.reason,
        "attempts": event.attempts, "next_attempt_at": when(event.next_attempt_at),
        "request_count": event.request_count, "size_bytes": event.size_bytes, "key_version": event.key_version,
        "received_at": when(event.received_at), "ended_at": when(event.ended_at),
    }  # fmt: skip
