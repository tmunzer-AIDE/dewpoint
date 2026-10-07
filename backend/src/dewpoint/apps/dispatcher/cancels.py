# SPDX-License-Identifier: Apache-2.0
"""Sending recorded cancels to Temporal (engine 2b spec §7.7): the dispatcher's, so the API has no Temporal client. A
started run with a recorded cancel, still running, gets one cancel request; the run then ends as cancelled through its
own end write (or the reconciler, §7.6). Ids reach it only through `cancel_candidates()`."""

from collections import Counter
from datetime import timedelta

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import budget
from dewpoint.apps.dispatcher.reconcile import namespace_answers
from dewpoint.core.db import tenant_scope
from dewpoint.engine.runtime.ids import run_workflow_id

log = structlog.get_logger("dewpoint.dispatcher")
BATCH = 50  # cancels per cycle
CALL_DEADLINE = timedelta(seconds=10)  # a cancel's: the SDK sets none (the 2b-4b plan's M1b)


async def send_cancels(sessionmaker: async_sessionmaker[AsyncSession], client: Client) -> dict[str, int]:
    """What happened, counted: `sent`, `closed` (its execution had already ended), `unsent` (tried again next cycle)."""
    async with sessionmaker() as s:
        picked = (await s.execute(text("select tenant_id, request_id from cancel_candidates(:n)"), {"n": BATCH})).all()
    counts: Counter[str] = Counter()
    with budget.passing("cancels") as admitted:
        for tenant_id, request_id in admitted(picked, key=lambda row: row[1]):
            happened = "sent"
            try:
                handle = client.get_workflow_handle(run_workflow_id(str(tenant_id), str(request_id)))
                await handle.cancel(rpc_timeout=CALL_DEADLINE)
            except RPCError as e:
                if not (e.status == RPCStatusCode.NOT_FOUND and await namespace_answers(client)):
                    log.warning("cancel_unsent", request_id=str(request_id), error=e.status.name)
                    counts["unsent"] += 1
                    continue
                happened = "closed"  # nothing left to cancel: the reconciler records its end
            except Exception as e:
                log.warning("cancel_unsent", request_id=str(request_id), error=type(e).__name__)
                counts["unsent"] += 1
                continue
            async with sessionmaker() as s, s.begin():
                await tenant_scope(s, tenant_id)
                await s.execute(
                    text("update run_requests set cancel_sent_at = statement_timestamp() where id = :i"),
                    {"i": request_id},
                )
            counts[happened] += 1
    if admitted.deferred:
        counts["deferred"] = admitted.deferred
    return dict(counts)
