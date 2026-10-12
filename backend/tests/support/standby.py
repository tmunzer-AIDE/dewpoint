# SPDX-License-Identifier: Apache-2.0
"""A synchronous standby that never answers, named on a test's Postgres for a block: a commit that writes waits for it
(under `synchronous_commit` on), with the locks its transaction holds, until the block ends and names none again.

The setting reaches commits only once the server has reloaded it (its checkpointer marks the standby defined), so the
block starts once a probe's commit is seen waiting; at its end the setting is reset and every waiting commit let go.
For a container of the test's own: the setting is the server's, every database's (tests in one worker run one at a
time)."""

import asyncio
import contextlib
from collections.abc import AsyncIterator

import asyncpg

PROBE_S = 0.3  # a probe's commit still waiting this long: the standby is waited for


async def _named(url: str, names: str | None) -> None:
    c = await asyncpg.connect(url)
    try:
        if names is None:
            await c.execute("ALTER SYSTEM RESET synchronous_standby_names")
        else:
            await c.execute(f"ALTER SYSTEM SET synchronous_standby_names = '{names}'")
        await c.execute("SELECT pg_reload_conf()")
    finally:
        await c.close()


@contextlib.asynccontextmanager
async def silent_standby(url: str) -> AsyncIterator[None]:
    """`url`: a plain `postgresql://` one, a superuser's."""
    probes: list[tuple[asyncpg.Connection, asyncio.Task[None]]] = []
    await _named(url, "nobody")
    try:
        for _ in range(50):
            probe = await asyncpg.connect(url)
            tx = probe.transaction()
            await tx.start()
            # a commit that writes (an xid alone writes nothing, and waits for no standby)
            await probe.fetchval("SELECT pg_logical_emit_message(true, 'dewpoint', 'probe')")
            committing = asyncio.create_task(tx.commit())
            probes.append((probe, committing))
            await asyncio.wait({committing}, timeout=PROBE_S)
            if not committing.done():
                break
        else:
            raise AssertionError("the standby was never waited for")
        yield
    finally:
        await _named(url, None)  # none named: every commit waiting for one is let go
        for probe, committing in probes:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(committing, 30)
            await probe.close()
