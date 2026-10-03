# SPDX-License-Identifier: Apache-2.0
"""Turning production runs off (engine 2b spec §2.2, §2.4), as `dewpoint_admin`: the gate goes off at once, audited,
and the command then waits for the starts already made to settle (started, or back in the queue), up to the
dispatcher's start deadline. A start still unsettled is reported unresolved: the gate stays off, the reconciler
settles it and audits that (§7.6), and the disable is never reported as fully settled meanwhile."""

import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.apps.dispatcher.dispatch import START_DEADLINE
from dewpoint.core.audit import service as audit
from dewpoint.core.models.requests import RunRequest

POLL_S = 0.25  # between looks at what's still starting


async def disable_production_runs(s: AsyncSession, *, actor_id: uuid.UUID | None) -> bool:
    """The gate off, in the caller's transaction, under the gate's exclusive lock, audited. Whether it was on."""
    was = bool((await s.execute(text("select disable_production_runs()"))).scalar_one())
    await audit.record(s, tenant_id=None, actor_id=actor_id, action="platform.production_runs.disable",
                       target_type="platform", target_id="production_runs", details={"was_on": was})  # fmt: skip
    return was


async def starting(s: AsyncSession) -> list[uuid.UUID]:
    """Every tenant's requests still `starting` (the admin's platform-wide read, 0019)."""
    found = await s.execute(select(RunRequest.id).where(RunRequest.status == "starting").order_by(RunRequest.id))
    return list(found.scalars())


async def disable_and_wait(
    sessionmaker: async_sessionmaker[AsyncSession], *, actor_id: uuid.UUID | None = None,
    deadline: timedelta = START_DEADLINE,
) -> list[uuid.UUID]:  # fmt: skip
    """The gate off, then the starts still unsettled once `deadline` has passed: none, when every one settled."""
    async with sessionmaker() as s, s.begin():
        await disable_production_runs(s, actor_id=actor_id)
    loop = asyncio.get_running_loop()
    until = loop.time() + deadline.total_seconds()
    while True:
        async with sessionmaker() as s:
            left = await starting(s)
        if not left or loop.time() >= until:
            return left
        await asyncio.sleep(POLL_S)
