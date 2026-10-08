# SPDX-License-Identifier: Apache-2.0
"""A user's cancel (engine 2b spec §7.7, §7.8), in its caller's transaction (the API's): a queued request is
cancelled at once, audited, with the row an earlier attempt wrote; a `starting` request or a running run has its cancel
recorded, once, for the dispatcher, which applies it when the start resolves or sends it to Temporal. The API needs no
Temporal client and no write on `runs`."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit import service as audit
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.tenancy import lifecycle

USER_CANCELLED = "user_cancelled"


class RequestNotFoundError(Exception):
    """No such request in this tenant. The message is fixed."""


async def cancel_request(s: AsyncSession, *, tenant_id: uuid.UUID, request_id: uuid.UUID, actor_id: uuid.UUID) -> str:
    """`cancelled` (it was queued), `requested` (recorded for the dispatcher), or `ended` (nothing left to cancel).
    Raises RequestNotFoundError, or TenantNotActiveError once an erasure started (it cancels what's left)."""
    await tenant_scope(s, tenant_id)
    await lifecycle.require_active(s, tenant_id)
    request = (
        await s.execute(
            select(RunRequest)
            .where(RunRequest.id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if request is None:
        raise RequestNotFoundError("No such run request.")
    if request.status == "queued":  # the dispatcher skips a request locked here, and re-reads it after
        now = datetime.now(UTC)
        request.status, request.reason, request.ended_at = "cancelled", USER_CANCELLED, now
        request.cancel_requested_at = now
        await s.flush()
        await s.execute(text("select end_unstarted_run(:i)"), {"i": request.id})
        await _audited(s, request, actor_id, "run.request.cancel")
        return "cancelled"
    if request.status == "starting" or (request.status == "started" and await _running(s, request.id)):
        if request.cancel_requested_at is None:
            request.cancel_requested_at = datetime.now(UTC)
            await _audited(s, request, actor_id, "run.cancel.requested")
        return "requested"
    return "ended"


async def _running(s: AsyncSession, run_id: uuid.UUID) -> bool:
    found = await s.execute(text("select status from runs where id = :i"), {"i": run_id})
    return found.scalar() == "running"


async def _audited(s: AsyncSession, request: RunRequest, actor_id: uuid.UUID, action: str) -> None:
    await audit.record(s, tenant_id=request.tenant_id, actor_id=actor_id, action=action, target_type="run_request",
                       target_id=str(request.id), details={"reason": USER_CANCELLED})  # fmt: skip
