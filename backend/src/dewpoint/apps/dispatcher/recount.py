# SPDX-License-Identifier: Apache-2.0
"""The recount of inbound-event counters (engine 2b spec §8.3; "Retained storage" in the 2b-3b outline), by the
leader. Each tenant `recount_candidates()` picks (at most every 10 minutes) is recounted in one transaction, under the
one lock order: the tenant's lifecycle lock shared, its endpoint rows in id order, its counter row, all held **before**
it counts, so no insert or match in flight is overwritten by a stale total. Every pending and retained counter that
drifted from what the events say is corrected and warned about."""

import uuid
from collections import Counter

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.apps.dispatcher.dispatch import tenant_lock
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.ingress import InboundEvent, TenantEventCounters, WebhookEndpoint

log = structlog.get_logger("dewpoint.dispatcher.recount")
BATCH = 20  # tenants a leader's cycle
FIELDS = ("pending_events", "pending_bytes", "retained_events", "retained_bytes")


async def _after_recount_locked() -> None:
    """Runs once a recount holds its tenant's rows, before it counts. A no-op; the race tests hold a recount here."""


async def _before_recount_commit() -> None:
    """Runs as a recount is about to commit its corrections. A no-op; the tests fail a transaction here."""


async def recount_once(sessionmaker: async_sessionmaker[AsyncSession], *, batch: int = BATCH) -> dict[str, int]:
    """The tenants due a recount, each recounted: how many, and how many rows were corrected. A recount that fails is
    logged by type and leaves its tenant for a later cycle."""
    async with sessionmaker() as s:
        query = text("select tenant_id from recount_candidates(:n)")
        picked: list[uuid.UUID] = list((await s.execute(query, {"n": batch})).scalars().all())
    counts: Counter[str] = Counter()
    for tenant_id in picked:
        try:
            counts["drifted"] += await recount_tenant(sessionmaker, tenant_id)
            counts["recounted"] += 1
        except Exception as e:
            log.error("event_recount_failed", tenant_id=str(tenant_id), error=type(e).__name__)
            counts["error"] += 1
    return dict(counts)


async def recount_tenant(sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID) -> int:
    """One tenant's counters recounted under its locks: the rows corrected. Each correction is warned about once it
    has committed, never for one rolled back (the owner's M3 review)."""
    drifts: list[dict[str, object]] = []
    async with sessionmaker() as s:
        async with s.begin():
            corrected = await _recount(s, tenant_id, drifts)
            await _before_recount_commit()
    for drift in drifts:  # committed
        log.warning("event_counters_drifted", **drift)
    return corrected


async def _recount(s: AsyncSession, tenant_id: uuid.UUID, drifts: list[dict[str, object]]) -> int:
    await tenant_scope(s, tenant_id)
    await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"),
                    {"k": tenant_lock(tenant_id)})  # fmt: skip
    endpoints = (
        await s.execute(
            select(WebhookEndpoint).where(WebhookEndpoint.tenant_id == tenant_id).order_by(WebhookEndpoint.id)
            .with_for_update().execution_options(populate_existing=True)
        )
    ).scalars().all()  # fmt: skip
    counter = (
        await s.execute(
            select(TenantEventCounters).where(TenantEventCounters.tenant_id == tenant_id).with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()  # fmt: skip
    if counter is None:
        return 0
    await _after_recount_locked()
    pending = InboundEvent.status == "pending"
    rows = await s.execute(
        select(
            InboundEvent.endpoint_id,
            func.count().filter(pending),
            func.coalesce(func.sum(InboundEvent.size_bytes).filter(pending), 0),
            func.count(),
            func.coalesce(func.sum(InboundEvent.size_bytes), 0),
        )
        .where(InboundEvent.tenant_id == tenant_id)
        .group_by(InboundEvent.endpoint_id)
    )
    by_endpoint = {row[0]: tuple(int(v) for v in row[1:]) for row in rows.all()}
    corrected = 0
    for endpoint in endpoints:
        truth = by_endpoint.get(endpoint.id, (0, 0, 0, 0))
        if await _correct(s, WebhookEndpoint, WebhookEndpoint.id == endpoint.id, endpoint, truth, drifts,
                          tenant_id=str(tenant_id), endpoint_id=str(endpoint.id)):  # fmt: skip
            corrected += 1
    totals = tuple(sum(values[i] for values in by_endpoint.values()) for i in range(len(FIELDS)))
    if await _correct(s, TenantEventCounters, TenantEventCounters.tenant_id == tenant_id, counter, totals, drifts,
                      tenant_id=str(tenant_id)):  # fmt: skip
        corrected += 1
    await s.execute(
        update(TenantEventCounters).where(TenantEventCounters.tenant_id == tenant_id)
        .values(recounted_at=func.now())
    )  # fmt: skip
    return corrected


async def _correct(s: AsyncSession, model: type, where: object, row: object, truth: tuple[int, ...],
                   drifts: list[dict[str, object]], **named: str) -> bool:  # fmt: skip
    stored = tuple(getattr(row, field) for field in FIELDS)
    if stored == truth:
        return False
    drifts.append({**named, "stored": dict(zip(FIELDS, stored, strict=True)),
                   "counted": dict(zip(FIELDS, truth, strict=True))})  # fmt: skip
    await s.execute(update(model).where(where).values(dict(zip(FIELDS, truth, strict=True))))  # type: ignore[arg-type]
    return True
