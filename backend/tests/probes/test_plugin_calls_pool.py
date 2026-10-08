# SPDX-License-Identifier: Apache-2.0
"""Plugin calls beside the activities on a worker's shared pool (the 2b-4b plan's M3, item 8; the final review's I4
moved only the calls' guards to a pool of their own): a worker's engines as `main.engines` makes them (the shared pool,
5 connections and 10 more on demand; the guards', 8), `ACTIVITIES` activities' transactions at once (each a step's
projection, as the store writes one) for `SECONDS`, first alone, then beside a stream of plugin calls 8 in flight, each
hook answered `HOOK_MS` late at its provider. Per projection: its time from asking for a connection to its commit; the
shared pool's most connections checked out at once; the calls done meanwhile.

A probe, run by hand on a quiet machine, never in CI; bounded by `SECONDS` twice. From `backend/`:

    DEWPOINT_PROBE=1 [DEWPOINT_PROBE_OUT=FILE] .venv/bin/pytest -p no:cacheprovider -n 0 -s \\
        tests/probes/test_plugin_calls_pool.py

Numbers depend on the machine; record them with it."""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, text

from dewpoint.apps.worker import main
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.db import make_sessionmaker
from dewpoint.engine.runtime.activities import ProjectInput
from tests.apps.worker.test_plugin_calls import NAMES, ask, server_for, service, setup
from tests.apps.worker.test_unconfirmed_steps import row
from tests.conftest import _url_for
from tests.core.runs.test_service import seeded_run
from tests.support.keys import FixtureKeys
from tests.support.netfakes import Request, serve

pytestmark = [
    pytest.mark.skipif(not os.environ.get("DEWPOINT_PROBE"), reason="a probe, run by hand (DEWPOINT_PROBE)"),
    pytest.mark.usefixtures("development_deployment"),
]
ACTIVITIES, SECONDS, HOOK_MS, CALLS = 30, 15.0, 50, 8


def _pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))]


class Peak:
    """The most connections a pool had checked out at once, while watched."""

    def __init__(self, engine: Any) -> None:
        self.now = self.most = 0
        pool = engine.sync_engine.pool
        event.listen(pool, "checkout", self._out)
        event.listen(pool, "checkin", self._in)

    def _out(self, *_: Any) -> None:
        self.now += 1
        self.most = max(self.most, self.now)

    def _in(self, *_: Any) -> None:
        self.now -= 1


async def _projections(store: DbRunStore, runs: list[tuple[uuid.UUID, uuid.UUID]]) -> list[float]:
    """Each run's projections, one after another, for SECONDS, all runs at once: each one's time."""
    times: list[float] = []
    stop = time.monotonic() + SECONDS

    async def one(tenant: uuid.UUID, run_id: uuid.UUID) -> None:
        step = 0
        while time.monotonic() < stop:
            step += 1
            begun = time.perf_counter()
            await store.project(ProjectInput(str(tenant), [row(run_id, step, "succeeded")]))
            times.append(time.perf_counter() - begun)

    await asyncio.gather(*(one(t, r) for t, r in runs))
    return times


def _summary(times: list[float], peak: Peak) -> dict[str, Any]:
    ms = [t * 1000 for t in times]
    return {"projections": len(ms), "per_s": round(len(ms) / SECONDS, 1), "p50_ms": round(_pct(ms, 0.5), 1),
            "p95_ms": round(_pct(ms, 0.95), 1), "p99_ms": round(_pct(ms, 0.99), 1), "max_ms": round(max(ms), 1),
            "shared_pool_most": peak.most}  # fmt: skip


async def test_projections_beside_plugin_calls_on_the_shared_pool(
    pg_url, _test_users, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    shared, guards = main.engines(_url_for(pg_url, "dewpoint_worker"))
    store = DbRunStore(make_sessionmaker(shared), FixtureKeys())
    runs = [await seeded_run(owner_sessionmaker, dispatch_sessionmaker) for _ in range(ACTIVITIES)]

    alone_peak = Peak(shared)
    alone = _summary(await _projections(store, runs), alone_peak)

    async def late(request: Request, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(HOOK_MS / 1000)
        await service(request, writer)

    async with serve(late, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        asking = asyncio.Event()

        async def keep_asking() -> int:
            asked = 0
            while not asking.is_set():
                await ask(api_sessionmaker, tenant, cid)
                asked += 1
            return asked

        for _ in range(CALLS * 4):  # a backlog before the window opens
            await ask(api_sessionmaker, tenant, cid)
        producer = asyncio.create_task(keep_asking())
        server = server_for(make_sessionmaker(shared), tenant, concurrency=CALLS, guards=make_sessionmaker(guards),
                            engine=shared)  # fmt: skip
        serving = asyncio.create_task(server.run())
        beside_peak = Peak(shared)
        beside = _summary(await _projections(store, runs), beside_peak)
        asking.set()
        server.stop()
        await asyncio.gather(serving, producer, return_exceptions=True)
    async with owner_sessionmaker() as s:
        done = (await s.execute(text("select count(*) from plugin_calls where tenant_id = :t and state = 'done'"),
                                {"t": tenant})).scalar_one()  # fmt: skip
    await shared.dispose()
    await guards.dispose()
    result = {"activities": ACTIVITIES, "seconds": SECONDS, "hook_ms": HOOK_MS, "alone": alone,
              "beside_calls": beside | {"calls_done": done, "calls_per_s": round(done / SECONDS, 1)}}  # fmt: skip
    print(json.dumps(result))
    out = os.environ.get("DEWPOINT_PROBE_OUT")
    if out:
        Path(out).write_text(json.dumps(result, indent=1))  # noqa: ASYNC240  # once, at the end
