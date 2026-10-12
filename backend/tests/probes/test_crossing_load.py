# SPDX-License-Identifier: Apache-2.0
"""A realistic crossing beside a loaded worker (the 2b-4b plan's M3, item 8; the owner's ruling on the M2
measurement): 10,000 claims a parent holds by grant, nested three levels (`LISTED` in the parent's value, the first
`MIDDLE` of them each nesting one `MIDDLE` claim, the first `DEEPEST` of those each nesting one `DEEPEST`: every claim
reached), each of `CLAIM_BYTES`, granted to a child through the grant activity's
own code (`claims._granted`, against its one-minute timeout), while `ACTIVITIES` activities project steps on the same
worker engines (`main.engines`). Then a run's `unconfirmed_batches` grown to `BATCHES`: what a projection holding
`running` rows (each checked against every closed batch, under the run row's share lock) and a batch's closing cost.

A probe, run by hand on a quiet machine, never in CI; bounded by its sizes. From `backend/`:

    DEWPOINT_PROBE=1 [DEWPOINT_PROBE_OUT=FILE] .venv/bin/pytest -p no:cacheprovider -n 0 -s \\
        tests/probes/test_crossing_load.py

Numbers depend on the machine; record them with it."""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.worker import main
from dewpoint.apps.worker.claims import _granted
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.claims import service
from dewpoint.core.db import make_sessionmaker
from dewpoint.engine.handles import ClaimRef
from dewpoint.engine.runtime.activities import CloseBatchInput, ProjectInput, UnconfirmedBatch
from tests.apps.worker.test_unconfirmed_steps import row
from tests.conftest import _url_for
from tests.core.claims.test_service import a_tenant
from tests.core.runs.test_service import seeded_run
from tests.support.keys import FixtureKeys

pytestmark = [
    pytest.mark.skipif(not os.environ.get("DEWPOINT_PROBE"), reason="a probe, run by hand (DEWPOINT_PROBE)"),
    pytest.mark.usefixtures("development_deployment"),
]
DEEPEST, MIDDLE, LISTED = 100, 1_000, 8_900  # 10,000 claims
CLAIM_BYTES = 1_024
ACTIVITIES = 30
BATCHES = (0, 100, 1_000, 10_000)
ROWS = 50  # `running` rows a projection holds
RESULT: dict[str, Any] = {}


def _pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))]


def _ms(times: list[float]) -> dict[str, float]:
    ms = [t * 1000 for t in times]
    return {"n": len(ms), "p50_ms": round(_pct(ms, 0.5), 1), "p95_ms": round(_pct(ms, 0.95), 1),
            "max_ms": round(max(ms), 1)} if ms else {"n": 0}  # fmt: skip


async def _projecting(store: DbRunStore, runs: list[tuple[uuid.UUID, uuid.UUID]], stop: asyncio.Event) -> list[float]:
    times: list[float] = []

    async def one(tenant: uuid.UUID, run_id: uuid.UUID) -> None:
        step = 0
        while not stop.is_set():
            step += 1
            begun = time.perf_counter()
            await store.project(ProjectInput(str(tenant), [row(run_id, step, "succeeded")]))
            times.append(time.perf_counter() - begun)

    await asyncio.gather(*(one(t, r) for t, r in runs))
    return times


async def test_a_ten_thousand_claim_crossing_beside_a_loaded_worker_and_a_runs_closed_batches(
    pg_url, _test_users, owner_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    shared, guards = main.engines(_url_for(pg_url, "dewpoint_worker"))
    store = DbRunStore(make_sessionmaker(shared), FixtureKeys())
    tenant, holder, parent, child = await a_tenant(owner_sessionmaker), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    pad = "x" * CLAIM_BYTES
    deepest = [uuid.uuid4() for _ in range(DEEPEST)]
    middle = [uuid.uuid4() for _ in range(MIDDLE)]
    listed = [uuid.uuid4() for _ in range(LISTED)]
    made = [service.NewClaim(c, {"v": n, "pad": pad}, (), holder, holder) for n, c in enumerate(deepest)]
    made += [service.NewClaim(c, {"v": n, "pad": pad, **({"in": ClaimRef(str(deepest[n])).to_json()}
                                                          if n < DEEPEST else {})}, (), holder, holder)
             for n, c in enumerate(middle)]  # fmt: skip
    made += [service.NewClaim(c, {"v": n, "pad": pad, **({"in": ClaimRef(str(middle[n])).to_json()}
                                                          if n < MIDDLE else {})}, (), holder, holder)
             for n, c in enumerate(listed)]  # fmt: skip
    began = time.perf_counter()
    await store.write(str(tenant), made, kind="output", step_id=None, iteration_key=None)
    every = [str(c.id) for c in made]
    await store.grant(str(tenant), granted_by=str(holder), to=str(parent), claim_ids=every, root_run_id=str(holder))
    seeded_s = time.perf_counter() - began
    value = {"xs": [ClaimRef(str(c)).to_json() for c in listed]}

    runs = [await seeded_run(owner_sessionmaker, dispatch_sessionmaker) for _ in range(ACTIVITIES)]
    stop = asyncio.Event()
    loading = asyncio.create_task(_projecting(store, runs, stop))
    await asyncio.sleep(2)  # the load running before the crossing
    begun = time.perf_counter()
    await _granted(store, str(tenant), str(parent), str(child), value, str(holder))
    crossing_s = time.perf_counter() - begun
    stop.set()
    beside = await loading
    async with owner_sessionmaker() as s:
        granted = (await s.execute(text("select count(*) from claim_grants where run_id = :c"), {"c": child})).scalar()
    RESULT["crossing"] = {"claims": len(made), "claim_bytes": CLAIM_BYTES, "seeded_s": round(seeded_s, 1),
                          "granted": granted, "crossing_s": round(crossing_s, 2), "timeout_s": 60,
                          "projections_beside": _ms(beside)}  # fmt: skip

    tenant_id, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    grown: dict[str, Any] = {}
    for size in BATCHES:
        batches = [{"scope": "", "loop": "l", "start": 2 * n, "end": 2 * n + 1} for n in range(size)]
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("update runs set unconfirmed_batches = cast(:b as jsonb) where id = :i"),
                            {"b": json.dumps(batches) if batches else None, "i": run_id})  # fmt: skip
        projections = []
        for k in range(20):  # rows of iterations outside every batch: each checked against all of them
            rows = [row(run_id, 1000 * k + n, "running", f"l:{2 * n + 1}") for n in range(ROWS)]
            begun = time.perf_counter()
            await store.project(ProjectInput(str(tenant_id), rows))
            projections.append(time.perf_counter() - begun)
        begun = time.perf_counter()
        closing = UnconfirmedBatch("", "l", 2 * size, 2 * size + 1)
        await store.close_batch(CloseBatchInput(str(tenant_id), str(run_id), closing))
        grown[str(size)] = {"projection_of_50_running": _ms(projections),
                            "close_batch_ms": round((time.perf_counter() - begun) * 1000, 1)}  # fmt: skip
    RESULT["unconfirmed_batches"] = grown
    await shared.dispose()
    await guards.dispose()
    print(json.dumps(RESULT))
    out = os.environ.get("DEWPOINT_PROBE_OUT")
    if out:
        Path(out).write_text(json.dumps(RESULT, indent=1))  # noqa: ASYNC240  # once, at the end
    assert granted == len(made)
