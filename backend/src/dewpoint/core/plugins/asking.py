# SPDX-License-Identifier: Apache-2.0
"""The API's side of a plugin call (plugins-3 D3): ask, wake the workers, wait for the answer, always delete the call.
The API runs no plugin code and sends nothing itself.

The caller ends its own transaction first: waiting holds no pooled connection and no lock (the 3a-2 review's finding
2). A process waits for at most `MAX_IN_FLIGHT` calls at once (`BusyError`), and a tenant may have at most
`MAX_PER_TENANT` calls outstanding (`TooManyCallsError`), so no tenant can use up the pool or the workers' slots."""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import tenant_scope
from dewpoint.core.plugins import calls

WAIT_S = 10.0  # how long the API waits for a worker's answer (D3)
FIRST_POLL_S, LAST_POLL_S = 0.05, 0.5  # the wait between reads grows from the first to the last
MAX_IN_FLIGHT = 16  # calls one API process waits for at once
MAX_PER_TENANT = 8  # a tenant's calls outstanding at once, across processes
_in_flight = 0


class BusyError(Exception):
    """This process already waits for `MAX_IN_FLIGHT` calls."""


class TooManyCallsError(Exception):
    """The tenant already has `MAX_PER_TENANT` calls outstanding."""


@dataclass(frozen=True)
class Outcome:
    """`answer` when a worker answered, `error` (a fixed code) when it refused, `timed_out` when none answered in
    time, `gone` when the call vanished meanwhile (its connection was deleted)."""

    answer: dict[str, Any] | None = None
    error: str | None = None
    timed_out: bool = False
    gone: bool = False


async def _ask(
    sessionmaker: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    ask: Callable[[AsyncSession], Awaitable[uuid.UUID]],
) -> uuid.UUID:
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        outstanding = await s.execute(
            text(
                "select count(*) from plugin_calls where tenant_id = :t and expires_at > now() "
                "and state in ('pending', 'claimed')"
            ),
            {"t": tenant_id},
        )
        if outstanding.scalar_one() >= MAX_PER_TENANT:
            raise TooManyCallsError()
        call_id = await ask(s)
        await calls.notify(s)
    return call_id


async def ask_and_wait(
    sessionmaker: async_sessionmaker[AsyncSession],
    keyring: Keyring,
    tenant_id: uuid.UUID,
    ask: Callable[[AsyncSession], Awaitable[uuid.UUID]],
) -> Outcome:
    global _in_flight
    if _in_flight >= MAX_IN_FLIGHT:
        raise BusyError()
    _in_flight += 1
    try:
        call_id = await _ask(sessionmaker, tenant_id, ask)
        try:
            return await _wait(sessionmaker, keyring, tenant_id, call_id)
        finally:
            async with sessionmaker() as s, s.begin():
                await tenant_scope(s, tenant_id)
                await calls.forget(s, tenant_id, call_id)
    finally:
        _in_flight -= 1


async def _wait(
    sessionmaker: async_sessionmaker[AsyncSession], keyring: Keyring, tenant_id: uuid.UUID, call_id: uuid.UUID
) -> Outcome:
    loop = asyncio.get_running_loop()
    until, pause = loop.time() + WAIT_S, FIRST_POLL_S
    while True:
        async with sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            found = await calls.read(s, tenant_id, call_id)
            if found is None:
                return Outcome(gone=True)
            if found.state == "failed":
                return Outcome(error=found.error or "unavailable")
            if found.state == "done" and found.result_ct is not None:
                raw = await keyring.decrypt(
                    s, tenant_id=tenant_id, purpose=calls.PURPOSE, context=str(call_id), blob=found.result_ct
                )
                answer = json.loads(raw)
                return Outcome(answer=answer) if isinstance(answer, dict) else Outcome(error="invalid_result")
        left = until - loop.time()
        if left <= 0:
            return Outcome(timed_out=True)
        await asyncio.sleep(min(pause, left))
        pause = min(pause * 2, LAST_POLL_S)
