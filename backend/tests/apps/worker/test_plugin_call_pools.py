# SPDX-License-Identifier: Apache-2.0
"""A worker's database connections with plugin calls in flight (the final review's I4). Each call in flight holds a
connection across its hook: its guard, which an erasure's step 1 waits for. Guards come from a pool of their own, one
connection a call, so with every call of a worker's concurrency in flight the pool its activities share still serves
them; guards in that shared pool instead leave its activities waiting (the control). A worker process's connections are
budgeted: its shared pool and its guards', nothing else."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from dewpoint.core.db import make_sessionmaker
from tests.apps.worker.test_plugin_calls import NAMES, ask, outcome, server_for, service, setup
from tests.conftest import _url_for
from tests.support.netfakes import Request, serve

CALLS = 8  # a worker's plugin calls in flight at once
SHARED = 10  # the activities' pool here: room for every call's own short transactions


@dataclass
class Held:
    """Calls whose hooks are held at their provider until `release` is set."""

    release: asyncio.Event
    server: Any
    serving: asyncio.Task[int]
    arrived: asyncio.Semaphore
    tenant: uuid.UUID
    calls: list[uuid.UUID]

    async def every_hook_held(self) -> None:
        for _ in range(CALLS):
            await self.arrived.acquire()

    async def end(self) -> None:
        self.release.set()
        await asyncio.gather(asyncio.wait_for(self.serving, 60), return_exceptions=True)
        await self.server.__aexit__(None, None, None)


@pytest.fixture
async def shared(pg_url: str, _test_users: None) -> AsyncIterator[AsyncEngine]:
    """The activities' pool, a short wait so a starved session fails fast."""
    engine = create_async_engine(_url_for(pg_url, "dewpoint_worker"), pool_size=SHARED, max_overflow=0, pool_timeout=2)
    yield engine
    await engine.dispose()


async def _held(owner: Any, api: Any, shared: AsyncEngine, guards: Callable[[Any], dict[str, Any]]) -> Held:
    arrived, release = asyncio.Semaphore(0), asyncio.Event()

    async def held(request: Request, writer: asyncio.StreamWriter) -> None:
        arrived.release()
        await release.wait()
        await service(request, writer)

    server = serve(held, tls_names=NAMES)
    fake = await server.__aenter__()
    tenant, cid = await setup(owner, fake.port)
    calls = [await ask(api, tenant, cid) for _ in range(CALLS)]
    sm = make_sessionmaker(shared)
    serving = asyncio.create_task(server_for(sm, tenant, concurrency=CALLS, **guards(sm)).serve_once())
    return Held(release, server, serving, arrived, tenant, calls)


async def _activities(shared: AsyncEngine) -> None:
    """As many activities at once as the shared pool holds, each holding its connection a second: with fewer free than
    that, the last wait past the pool's two seconds and fail."""

    async def one() -> None:
        async with make_sessionmaker(shared)() as s:
            await s.execute(text("select 1"))
            await asyncio.sleep(1)

    await asyncio.gather(*(one() for _ in range(SHARED)))


async def test_every_call_in_flight_leaves_the_activities_pool_to_its_activities(
    owner_sessionmaker, api_sessionmaker, shared, pg_url
) -> None:
    guard_pool = create_async_engine(_url_for(pg_url, "dewpoint_worker"), pool_size=CALLS, max_overflow=0)
    held = await _held(
        owner_sessionmaker, api_sessionmaker, shared, lambda _: {"guards": make_sessionmaker(guard_pool)}
    )
    try:
        await asyncio.wait_for(held.every_hook_held(), 15)  # all eight in flight, each holding its guard
        assert guard_pool.pool.checkedout() == CALLS  # type: ignore[attr-defined]
        await asyncio.wait_for(_activities(shared), 5)  # the whole shared pool
    finally:
        await held.end()
        await guard_pool.dispose()
    assert [(await outcome(api_sessionmaker, held.tenant, call))[0] for call in held.calls] == ["done"] * CALLS


async def test_guards_in_the_shared_pool_would_leave_the_activities_waiting(
    owner_sessionmaker, api_sessionmaker, shared
) -> None:
    """The control: the same calls with their guards in the activities' pool."""
    held = await _held(owner_sessionmaker, api_sessionmaker, shared, lambda sm: {"guards": sm})
    try:
        await asyncio.wait_for(held.every_hook_held(), 15)  # all eight in flight, their guards in the shared pool
        with pytest.raises(PoolTimeoutError):  # only two of its ten connections left: activities fail waiting
            await asyncio.wait_for(_activities(shared), 10)
    finally:
        await held.end()


def test_a_worker_process_opens_at_most_its_budgeted_connections(pg_url: str) -> None:
    from dewpoint.apps.worker import main

    shared_engine, guard_engine = main.engines(_url_for(pg_url, "dewpoint_worker"))
    try:
        pools = [(e.pool.size(), e.pool._max_overflow) for e in (shared_engine, guard_engine)]  # type: ignore[attr-defined]
        assert (sum(size + overflow for size, overflow in pools), pools[1]) == (
            main.CONNECTIONS,
            (main.PLUGIN_CALLS, 0),
        )
        assert main.CONNECTIONS == 23
    finally:
        asyncio.run(shared_engine.dispose())
        asyncio.run(guard_engine.dispose())
