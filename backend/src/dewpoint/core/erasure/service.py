# SPDX-License-Identifier: Apache-2.0
"""A tenant's erasure, its start, stop and retry (engine 2b spec §6.5; the 2b-4 outline's "Tenant erasure", D3).

Starting it is step 1, in one transaction, under the tenant's lifecycle lock taken exclusively: the tenant marked
`erasing`, its schedules' generations raised (their sync then only pauses or deletes them), its record created, and
the start audited. The exclusive lock waits for every writer that read `active` to commit or roll back; every writer
after it reads `erasing` and is refused. Irreversible from then on (D3a): an operator stops an erasure (audited; the
tenant stays `erasing`, every refusal still applies) or retries it, never reverses it. The retention process carries
it on (`apps.erasure`)."""

import uuid

from sqlalchemy import insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit import service as audit
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.erasure import TenantErasure
from dewpoint.core.models.schedules import Schedule
from dewpoint.core.tenancy import lifecycle


class TenantNotFoundError(Exception):
    """No such tenant. The message is fixed."""


class NotErasableError(Exception):
    """The tenant isn't active: an erasure is already under way, or done. The message is fixed."""


class NoErasureError(Exception):
    """The tenant has no erasure under way. The message is fixed."""


async def _after_lock() -> None:
    """Runs once step 1 holds the tenant's lifecycle lock. A no-op; the race tests pause here."""


async def start(s: AsyncSession, *, tenant_id: uuid.UUID, requested_by: uuid.UUID) -> TenantErasure:
    """Step 1, in the caller's transaction (which must commit it): raises TenantNotFoundError, NotErasableError."""
    await lifecycle.hold_calls_exclusive(s, tenant_id)  # waits for plugin calls in flight, before the lifecycle lock
    await lifecycle.hold_exclusive(s, tenant_id)
    await _after_lock()
    status = (await s.execute(text("select tenant_status(:t)"), {"t": tenant_id})).scalar()
    if status is None:
        raise TenantNotFoundError("No such tenant.")
    if status != "active":
        raise NotErasableError("This tenant is already being erased.")
    await tenant_scope(s, tenant_id)
    await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": tenant_id})
    raised = await s.execute(
        update(Schedule).where(Schedule.tenant_id == tenant_id).values(generation=Schedule.generation + 1)
    )
    # its tenant and requester only, the columns the API may write (the final review's I2): every other one a default
    record = (await s.execute(insert(TenantErasure).values(tenant_id=tenant_id, requested_by=requested_by)
                              .returning(TenantErasure))).scalar_one()  # fmt: skip
    await audit.record(s, tenant_id=tenant_id, actor_id=requested_by, action="tenant.erasure.start",
                       target_type="tenant", target_id=str(tenant_id),
                       details={"schedules": int(raised.rowcount)})  # type: ignore[attr-defined]  # fmt: skip
    return record


async def _record(s: AsyncSession, tenant_id: uuid.UUID) -> TenantErasure:
    found = (
        await s.execute(
            select(TenantErasure).where(TenantErasure.tenant_id == tenant_id).with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()  # fmt: skip
    if found is None or found.completed_at is not None:
        raise NoErasureError("This tenant has no erasure under way.")
    await tenant_scope(s, tenant_id)  # its audit entries are the tenant's
    return found


async def stop(s: AsyncSession, *, tenant_id: uuid.UUID, stopped_by: uuid.UUID) -> TenantErasure:
    """An operator's stop: the retention process leaves it where it is; the tenant stays `erasing`. Raises
    NoErasureError."""
    record = await _record(s, tenant_id)
    if record.stopped_at is None:
        record.stopped_at = (await s.execute(text("select statement_timestamp()"))).scalar_one()
        record.stopped_by = stopped_by
        await audit.record(s, tenant_id=tenant_id, actor_id=stopped_by, action="tenant.erasure.stop",
                           target_type="tenant", target_id=str(tenant_id), details={"step": record.step})  # fmt: skip
    return record


async def retry(s: AsyncSession, *, tenant_id: uuid.UUID, actor_id: uuid.UUID) -> TenantErasure:
    """An operator's retry: clears a stop and the backoff, so the next pass takes it at its recorded step. Raises
    NoErasureError."""
    record = await _record(s, tenant_id)
    record.stopped_at, record.stopped_by = None, None
    record.next_attempt_at = (await s.execute(text("select statement_timestamp()"))).scalar_one()
    await audit.record(s, tenant_id=tenant_id, actor_id=actor_id, action="tenant.erasure.retry",
                       target_type="tenant", target_id=str(tenant_id), details={"step": record.step})  # fmt: skip
    return record
