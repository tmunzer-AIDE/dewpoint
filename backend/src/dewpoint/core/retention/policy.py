# SPDX-License-Identifier: Apache-2.0
"""A tenant's retention (engine 2b spec §10.1): `runs_days`, the default unless its admins set it within the platform's
bounds. Read and set under the caller's tenant scope."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit import service as audit
from dewpoint.core.models.retention import TenantRetention

DEFAULT_RUNS_DAYS = 30
MIN_RUNS_DAYS, MAX_RUNS_DAYS = 1, 365


async def runs_days(s: AsyncSession, tenant_id: uuid.UUID) -> int:
    found = await s.scalar(select(TenantRetention.runs_days).where(TenantRetention.tenant_id == tenant_id))
    return DEFAULT_RUNS_DAYS if found is None else found


async def set_runs_days(s: AsyncSession, tenant_id: uuid.UUID, days: int, *, actor_id: uuid.UUID) -> int:
    """The tenant's retention set to `days`, audited with what it was. Concurrent changes take turns on its row."""
    if not MIN_RUNS_DAYS <= days <= MAX_RUNS_DAYS:
        raise ValueError("runs_days is outside the platform's bounds")
    await s.execute(insert(TenantRetention).values(tenant_id=tenant_id).on_conflict_do_nothing())
    was = (
        await s.execute(
            select(TenantRetention.runs_days).where(TenantRetention.tenant_id == tenant_id).with_for_update()
        )
    ).scalar_one()
    await s.execute(
        update(TenantRetention)
        .where(TenantRetention.tenant_id == tenant_id)
        .values(runs_days=days, updated_by=actor_id, updated_at=func.now())
    )
    details: dict[str, object] = {"runs_days": days, "was": was}
    await audit.record(s, tenant_id=tenant_id, actor_id=actor_id, action="tenant.retention.update",
                       target_type="tenant", target_id=str(tenant_id), details=details)  # fmt: skip
    return was
