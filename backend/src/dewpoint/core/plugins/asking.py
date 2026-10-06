# SPDX-License-Identifier: Apache-2.0
"""The API's side of a plugin call (plugins-3 D3): ask, wake the workers, wait for the answer, always delete the call.
The API runs no plugin code and sends nothing itself."""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import tenant_scope
from dewpoint.core.plugins import calls

WAIT_S = 10.0  # how long the API waits for a worker's answer (D3)
EVERY_S = 0.1


@dataclass(frozen=True)
class Outcome:
    """`answer` when a worker answered, `error` (a fixed code) when it refused, `timed_out` when none answered in
    time, `gone` when the call vanished meanwhile (its connection was deleted)."""

    answer: dict[str, Any] | None = None
    error: str | None = None
    timed_out: bool = False
    gone: bool = False


async def ask_and_wait(
    sessionmaker: async_sessionmaker[AsyncSession],
    keyring: Keyring,
    tenant_id: uuid.UUID,
    ask: Callable[[AsyncSession], Awaitable[uuid.UUID]],
) -> Outcome:
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        call_id = await ask(s)
        await calls.notify(s)
    try:
        loop = asyncio.get_running_loop()
        until = loop.time() + WAIT_S
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
            if loop.time() >= until:
                return Outcome(timed_out=True)
            await asyncio.sleep(EVERY_S)
    finally:
        async with sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            await calls.forget(s, tenant_id, call_id)
