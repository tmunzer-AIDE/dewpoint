# SPDX-License-Identifier: Apache-2.0
"""The dev CLI's run (engine 2b spec §7.7): it admits a workflow's active version with the source `dev`, in its own
transaction, as the dispatch role, and the dispatcher starts it like any other request. Its wait is bounded and
reports the end the database records (the request's, when it never started; else its run's), not merely a start."""

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.apps import admission
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.runs import Run
from dewpoint.engine.runtime.activities import LIVE, SIMULATE

ENDED = ("cancelled", "refused", "dead")  # a request's own ends: it never started


@dataclass(frozen=True)
class Ended:
    """What ended: the `request` (it never started) with its status and reason, or its `run`, with its own."""

    what: str
    status: str
    code: str | None
    message: str | None


async def admit(
    sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID,
    input: dict[str, Any], simulate: bool, idempotency_key: str,
) -> RunRequest:  # fmt: skip
    """The request, queued. Raises admission's errors, AdmissionRefusedError with its reason and messages first."""
    async with sessionmaker() as s, s.begin():
        admitted = await admission.admit_request(
            s, keys, tenant_id=tenant_id, workflow_id=workflow_id, source="dev", actor_id=None,
            mode=SIMULATE if simulate else LIVE, idempotency_key=idempotency_key, input=input,
        )  # fmt: skip
        return admitted.request


async def ended(
    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, request_id: uuid.UUID
) -> Ended | None:
    """The end the database records for a request, or None while it's queued, starting or running."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        request = await s.get(RunRequest, request_id)
        if request is None:
            raise LookupError("No such run request.")
        if request.status in ENDED:
            return Ended("request", request.status, request.reason, None)
        if request.status != "started":
            return None
        run = await s.get(Run, request_id)
        if run is None or run.status == "running":
            return None
        return Ended("run", run.status, run.error_code, run.error_message)


async def wait_for_end(
    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, request_id: uuid.UUID, *, within: float,
    poll: float = 0.5,
) -> Ended | None:  # fmt: skip
    """The recorded end, looked for until `within` seconds have passed; None if there's none by then."""
    loop = asyncio.get_running_loop()
    until = loop.time() + within
    while True:
        found = await ended(sessionmaker, tenant_id, request_id)
        if found is not None or loop.time() >= until:
            return found
        await asyncio.sleep(poll)
