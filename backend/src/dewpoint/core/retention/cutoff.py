# SPDX-License-Identifier: Apache-2.0
"""The retention cutoff on user-facing reads (engine 2b spec §10.1; ruling D4): data leaves every read at once, whatever
is still stored. A run tree's data is past the cutoff `runs_days` after its root ended; a terminal request's and a
terminal event's, after they ended. Nothing that hasn't ended is ever past it.

Only the API's reads apply it, in their own queries: never the engine's shared helpers (admission's idempotency
lookup, the envelope's reader, the end write) nor a row-level policy, which admission inside the API would also meet.
The cutoff is reckoned on the database's clock."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute

from dewpoint.core.models.ingress import InboundEvent
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.runs import Run
from dewpoint.core.retention import policy

Cutoff = ColumnElement[Any]  # a timestamp: what ended at or before it is past retention


async def cutoff(s: AsyncSession, tenant_id: uuid.UUID) -> Cutoff:
    return func.statement_timestamp() - timedelta(days=await policy.runs_days(s, tenant_id))


def kept(ended_at: QueryableAttribute[datetime | None], at: Cutoff) -> ColumnElement[bool]:
    """Within retention: not ended, or ended after the cutoff."""
    return or_(ended_at.is_(None), ended_at > at)


async def run_kept(s: AsyncSession, at: Cutoff, run: Run) -> bool:
    """A run, a sub-run included, whose tree's root ended within retention or hasn't ended."""
    return bool(await s.scalar(select(kept(Run.ended_at, at)).where(Run.id == run.root_run_id)))


async def request_kept(s: AsyncSession, at: Cutoff, request: RunRequest) -> bool:
    """A request that started follows its run's tree, and one with no run to follow is past it (it fails closed); any
    other, when it ended."""
    if request.status == "started":
        run = await s.get(Run, request.id)
        return run is not None and await run_kept(s, at, run)
    return bool(await s.scalar(select(kept(RunRequest.ended_at, at)).where(RunRequest.id == request.id)))


async def event_kept(s: AsyncSession, at: Cutoff, event: InboundEvent) -> bool:
    return bool(await s.scalar(select(kept(InboundEvent.ended_at, at)).where(InboundEvent.id == event.id)))
