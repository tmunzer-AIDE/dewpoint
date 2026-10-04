# SPDX-License-Identifier: Apache-2.0
"""Matching inbound events (engine 2b spec §8.3; "Functions and lock order" in the 2b-3b outline), in every
dispatcher, only while the gate is on.

`event_candidates(n)` picks pending events, ids only and locking nothing, fair across tenants. Each is then matched in
a transaction of its own, under the one lock order: the gate's lock and the tenant's lifecycle lock, both shared (the
gate's disable and 2b-4's erasure take them exclusively), with the gate, the recorded environment and the tenant
rechecked under them; the event's endpoint row; the tenant's counter row; and only then the event row, `FOR UPDATE
SKIP LOCKED`, rechecked still pending and due (another dispatcher may have finished it). Holding the endpoint's row
serializes ingress and matching on one endpoint.

The event is opened with the tenant's private key and, for each enabled binding of its endpoint whose filter holds, in
workflow-id order (§7.2), one request is admitted: source `webhook`, key `evt:<event id>:<workflow id>`, the event as
the trigger. Admission freezes it or records it `refused`; either is a request. The event is recorded `matched` with
its request count, or `unmatched`, and its pending counters are released, together. A recheck that fails changes
nothing; more enabled bindings than the cap (refused when they're written) wait, with an alert."""

import json
import uuid
from collections import Counter
from datetime import timedelta

import structlog
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.apps import admission
from dewpoint.apps.dispatcher.dispatch import GATE_LOCK, tenant_lock
from dewpoint.core.crypto import events
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.db import tenant_scope
from dewpoint.core.ingress import keys as event_keys
from dewpoint.core.ingress.filters import matches
from dewpoint.core.models.ingress import InboundEvent, TenantEventCounters, TriggerBinding, WebhookEndpoint
from dewpoint.core.models.platform import PlatformSettings
from dewpoint.core.models.tenancy import Tenant
from dewpoint.core.platform.service import PRODUCTION
from dewpoint.core.plugins import lifecycle
from dewpoint.engine.runtime.activities import LIVE

log = structlog.get_logger("dewpoint.dispatcher.matching")
BATCH = 50  # events a cycle (§15, provisional)
MAX_BINDINGS = 20  # an endpoint's enabled bindings, refused past it when written, rechecked here
WAIT = timedelta(minutes=1)  # a wait that's no fault of the event's: retried after it, its attempts untouched
SOURCE = "webhook"
GATE_OFF = "gate_off"
ENVIRONMENT_NOT_RECORDED = "environment_not_recorded"
TENANT_ERASING = "tenant_erasing"
SKIPPED = "skipped"
FAN_OUT_EXCEEDED = "fan_out_exceeded"
ROLLED_BACK = (GATE_OFF, ENVIRONMENT_NOT_RECORDED, TENANT_ERASING, SKIPPED)


class Verified:
    """The tenants' keypair versions that have opened an event in this process: a version that has is known good."""

    def __init__(self) -> None:
        self._versions: set[tuple[uuid.UUID, int]] = set()

    def add(self, tenant_id: uuid.UUID, version: int) -> None:
        self._versions.add((tenant_id, version))

    def __contains__(self, item: object) -> bool:
        return item in self._versions


async def _after_event_locked() -> None:
    """Runs once a match holds its event's row. A no-op; the race tests hold a match here."""


def gate_off(platform: PlatformSettings | None) -> str | None:
    """Why nothing is matched now, or None: no recorded environment, or a production deployment's runs off."""
    if platform is None:
        return ENVIRONMENT_NOT_RECORDED
    if platform.environment == PRODUCTION and not platform.production_runs:
        return GATE_OFF
    return None


async def _lock(s: AsyncSession, key: str) -> None:
    await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": key})


async def match_once(
    sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource, verified: Verified, *, batch: int = BATCH
) -> dict[str, int]:
    """One cycle's matching: nothing while the gate is off; otherwise each candidate in turn. What happened, counted.
    A match that fails (a bug, an outage) is logged by type and leaves its event as it was."""
    async with sessionmaker() as s:
        waiting = gate_off(await s.get(PlatformSettings, 1))
        if waiting is not None:
            return {waiting: 1}
        query = text("select tenant_id, event_id, endpoint_id from event_candidates(:n)")
        picked = (await s.execute(query, {"n": batch})).all()
    counts: Counter[str] = Counter()
    for tenant_id, event_id, endpoint_id in picked:
        try:
            counts[await match_event(sessionmaker, keys, verified, tenant_id=tenant_id, event_id=event_id,
                                     endpoint_id=endpoint_id)] += 1  # fmt: skip
        except Exception as e:
            log.error("event_match_failed", tenant_id=str(tenant_id), event_id=str(event_id), error=type(e).__name__)
            counts["error"] += 1
    return dict(counts)


async def match_event(
    sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource, verified: Verified, *, tenant_id: uuid.UUID,
    event_id: uuid.UUID, endpoint_id: uuid.UUID,
) -> str:  # fmt: skip
    """One event's matching transaction: `matched`, `unmatched`, or why it waits or was passed by."""
    async with sessionmaker() as s, s.begin():
        outcome = await _match(s, keys, verified, tenant_id, event_id, endpoint_id)
        if outcome in ROLLED_BACK:
            await s.rollback()
        return outcome


async def _match(
    s: AsyncSession, keys: KeySource, verified: Verified, tenant_id: uuid.UUID, event_id: uuid.UUID,
    endpoint_id: uuid.UUID,
) -> str:  # fmt: skip
    await lifecycle.assert_read_committed(s)
    await tenant_scope(s, tenant_id)
    await _lock(s, GATE_LOCK)
    await _lock(s, tenant_lock(tenant_id))
    waiting = gate_off(await s.get(PlatformSettings, 1, populate_existing=True))
    if waiting is not None:
        return waiting
    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
    if tenant is None or tenant.status != "active":
        return TENANT_ERASING
    endpoint = (
        await s.execute(
            select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id).with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()  # fmt: skip
    if endpoint is None:
        return SKIPPED
    await s.execute(select(TenantEventCounters.tenant_id).where(TenantEventCounters.tenant_id == tenant_id)
                    .with_for_update())  # fmt: skip
    event = (
        await s.execute(
            select(InboundEvent)
            .where(
                InboundEvent.id == event_id,
                InboundEvent.endpoint_id == endpoint_id,
                InboundEvent.status == "pending",
                or_(InboundEvent.next_attempt_at.is_(None), InboundEvent.next_attempt_at <= func.statement_timestamp()),
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if event is None:
        return SKIPPED
    await _after_event_locked()
    private = await event_keys.private_key(s, keys, tenant_id, event.key_version)
    plaintext = events.open_sealed(private, tenant_id=tenant_id, endpoint_id=endpoint_id, event_id=event.id,
                                   blob=event.sealed)  # fmt: skip
    verified.add(tenant_id, event.key_version)
    payload = json.loads(plaintext)
    bindings = (
        await s.execute(
            select(TriggerBinding)
            .where(TriggerBinding.endpoint_id == endpoint_id, TriggerBinding.enabled.is_(True))
            .order_by(TriggerBinding.workflow_id)
            .limit(MAX_BINDINGS + 1)
        )
    ).scalars().all()  # fmt: skip
    if len(bindings) > MAX_BINDINGS:
        log.error("event_fan_out_exceeded", endpoint_id=str(endpoint_id), event_id=str(event.id))
        event.next_attempt_at = func.statement_timestamp() + WAIT
        await s.flush()
        return FAN_OUT_EXCEEDED
    admitted = 0
    for binding in bindings:
        if not matches(binding.filter, payload):
            continue
        await admission.admit_request(
            s, keys, tenant_id=tenant_id, workflow_id=binding.workflow_id, source=SOURCE, actor_id=None, mode=LIVE,
            idempotency_key=f"evt:{event.id}:{binding.workflow_id}", input=payload,
            details={"endpoint_id": str(endpoint_id), "event_id": str(event.id), "binding_id": str(binding.id)},
        )  # fmt: skip
        admitted += 1
    event.status = "matched" if admitted else "unmatched"
    event.request_count = admitted
    event.ended_at = func.statement_timestamp()
    await release(s, tenant_id, endpoint_id, event.size_bytes)
    await s.flush()
    return event.status


async def release(s: AsyncSession, tenant_id: uuid.UUID, endpoint_id: uuid.UUID, size: int, events_n: int = 1) -> None:
    """An event's pending counters released, on its endpoint and its tenant, whose rows the caller holds. Never below
    zero: a drift the recount corrects doesn't block an event's end."""
    for model, where in ((WebhookEndpoint, WebhookEndpoint.id == endpoint_id),
                         (TenantEventCounters, TenantEventCounters.tenant_id == tenant_id)):  # fmt: skip
        await s.execute(
            update(model).where(where).values(
                pending_events=func.greatest(model.pending_events - events_n, 0),
                pending_bytes=func.greatest(model.pending_bytes - size, 0),
            )
        )  # fmt: skip
