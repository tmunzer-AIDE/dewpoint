# SPDX-License-Identifier: Apache-2.0
"""What every writer of inbound events and their counters shares (engine 2b spec §8.3; "Functions and lock order" in
the 2b-3b outline): the tenant's lifecycle lock, taken shared (2b-4's erasure takes it exclusively), the first lock
any of them takes after the gate's; and releasing an event's pending counters, on its endpoint's row and its tenant's,
which the caller holds by then."""

import uuid

from sqlalchemy import func, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.models.ingress import TenantEventCounters, WebhookEndpoint


def tenant_lock(tenant_id: uuid.UUID) -> str:
    """The tenant's lifecycle lock: the dispatcher's starting transaction takes the same one."""
    return f"dewpoint:tenant:{tenant_id}"


async def lock_tenant_shared(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": tenant_lock(tenant_id)})


async def release(s: AsyncSession, tenant_id: uuid.UUID, endpoint_id: uuid.UUID, size: int, events_n: int = 1) -> None:
    """`events_n` events' pending counters (`size` bytes in all) released, on their endpoint and their tenant. Never
    below zero: a drift the recount corrects doesn't block an event's end."""
    for model, where in ((WebhookEndpoint, WebhookEndpoint.id == endpoint_id),
                         (TenantEventCounters, TenantEventCounters.tenant_id == tenant_id)):  # fmt: skip
        await s.execute(
            update(model).where(where).values(
                pending_events=func.greatest(model.pending_events - events_n, 0),
                pending_bytes=func.greatest(model.pending_bytes - size, 0),
            )
        )  # fmt: skip
