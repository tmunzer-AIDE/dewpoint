# SPDX-License-Identifier: Apache-2.0
"""The misses pass's due query, at scale (the owner's review of the 2b-4b M1 checkpoint 5, M3): its due filter
(`misses_checked_at` four minutes old) isn't its index's bound, so with fewer than 50 incarnations due the query walks
every incarnation that may still miss a firing, checking each one's row. Measured here at 2,000 to 200,000 such
incarnations, 0 or 10 of them due, those due least lately tried (the steady state: they come first in the index's
order) or most lately (reads that keep failing: they come last), and the steady state with every row's older version
left in place. For each: the plan its statement ran with (`auto_explain` on the function's own call, nested statements
included, its buffers: the first read since the shape was made, so before any read cleaned what it left), then its
time as the dispatcher calls it, a pooled connection held throughout (its first call apart). A run by hand, never in
CI (skipped unless `DEWPOINT_PROBE` is set); its results go to `DEWPOINT_PROBE_OUT` (JSON). From `backend/`:

    DEWPOINT_PROBE=1 DEWPOINT_PROBE_OUT=misses.json .venv/bin/pytest tests/probes/test_misses_due_cost.py -p no:randomly

These are this machine's numbers, on a test container: an order of magnitude, not a supported figure."""

import json
import math
import os
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text

from tests.core.retention.support import sql, tenant

pytestmark = pytest.mark.skipif(not os.environ.get("DEWPOINT_PROBE"), reason="a probe, run by hand (DEWPOINT_PROBE)")
SIZES = (2_000, 10_000, 50_000, 200_000)
# Shapes: none due; 10 due, least lately tried (the steady state) or most (reads that keep failing); and the steady
# state not vacuumed since every row was read once (non-HOT updates: each read leaves a dead row and index entry)
SHAPES = {"none due": None, "10 due, first": "first", "10 due, last": "last", "10 due, first, unvacuumed": "dead"}
CALLS = 30  # timed calls a shape
RESULTS: list[dict[str, Any]] = []


async def _seeded(owner: Any, n: int) -> uuid.UUID:
    """`n` schedules of a tenant of their own, each with one incarnation sent an unpause (so it may miss a firing), read
    a minute ago: none due."""
    ctx = await tenant(owner)
    await sql(owner, "alter table schedules disable trigger schedules_inventoried")
    try:
        await sql(owner, "insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by, "
                  "generation, synced_generation) select gen_random_uuid(), :t, :w, 3600, 'live', '\\x01', :u, 1, 1 "
                  "from generate_series(1, :n)", t=ctx["t"], w=ctx["w"], u=ctx["u"], n=n)  # fmt: skip
    finally:
        await sql(owner, "alter table schedules enable trigger schedules_inventoried")
    await sql(owner, "insert into schedule_incarnations (temporal_id, tenant_id, schedule_id, number, unpause_sent_at, "
              "misses_checked_at, misses_tried_at) select 't:' || s.tenant_id || ':sched:' || s.id || '~1', "
              "s.tenant_id, s.id, 1, now() - interval '1 hour', now() - interval '1 minute', "
              "now() - interval '1 minute' "
              "from schedules s where s.tenant_id = :t", t=ctx["t"])  # fmt: skip
    return ctx["t"]


async def _shaped(owner: Any, url: str, t: uuid.UUID, shape: str | None) -> None:
    """None due; or 10 due (read ten minutes ago), tried least lately (`first`, `dead`) or just now (`last`). Vacuumed
    after, but for `dead`, analyzed only: its rows' every older version left in place, as between autovacuums."""
    await sql(owner, "update schedule_incarnations set misses_checked_at = now() - interval '1 minute', "
              "misses_tried_at = now() - interval '1 minute' where tenant_id = :t", t=t)  # fmt: skip
    if shape is not None:
        tried = "now()" if shape == "last" else "now() - interval '10 minutes'"
        await sql(owner, "update schedule_incarnations set misses_checked_at = now() - interval '10 minutes', "
                  f"misses_tried_at = {tried} where temporal_id in (select temporal_id from schedule_incarnations "
                  "where tenant_id = :t order by temporal_id limit 10)", t=t)  # fmt: skip
    c = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    try:  # outside a transaction: the updates' dead rows cleared, as autovacuum would in time
        await c.execute("ANALYZE schedule_incarnations" if shape == "dead" else "VACUUM ANALYZE schedule_incarnations")
    finally:
        await c.close()


def _nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [node, *(n for child in node.get("Plans", []) for n in _nodes(child))]


async def _plan(url: str) -> dict[str, Any]:
    """The plan the function's own statement ran with (planned as a function's is, its limit a parameter), as
    `auto_explain` reports it, nested statements included."""
    c = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    said: list[str] = []
    c.add_log_listener(lambda _c, message: said.append(message.message))
    try:
        await c.execute("LOAD 'auto_explain'")
        for setting in ("log_min_duration = 0", "log_analyze = on", "log_buffers = on", "log_nested_statements = on",
                        "log_format = json", "log_level = notice"):  # fmt: skip
            await c.execute(f"SET auto_explain.{setting}")
        await c.fetch("select tenant_id, temporal_id from incarnation_miss_candidates(50)")
    finally:
        await c.close()
    [(head, inner)] = [(m.split("\n", 1)[0], json.loads(m.split("\n", 1)[1])) for m in said
                       if "schedule_incarnations" in m]  # fmt: skip
    nodes = _nodes(inner["Plan"])
    return {"nodes": [n["Node Type"] + (f" ({n['Index Name']})" if n.get("Index Name") else "") for n in nodes],
            "removed_by_filter": sum(n.get("Rows Removed by Filter", 0) for n in nodes),
            "shared_hit": inner["Plan"].get("Shared Hit Blocks"),
            "shared_read": inner["Plan"].get("Shared Read Blocks"),
            "duration_ms": float(head.split("duration:", 1)[1].split("ms", 1)[0]),
            "rows": inner["Plan"]["Actual Rows"]}  # fmt: skip


async def _timed(dispatch: Any) -> dict[str, float]:
    """The query as the misses pass makes it, as `dewpoint_dispatch`: a pooled connection held from checkout to its
    rows."""
    query = text("select tenant_id, temporal_id from incarnation_miss_candidates(:n)")
    took = []
    for _ in range(CALLS):
        started = time.perf_counter()
        async with dispatch() as s:
            (await s.execute(query, {"n": 50})).all()
        took.append((time.perf_counter() - started) * 1000)
    first, rest = round(took[0], 2), sorted(took[1:])
    return {"first_ms": first, "median_ms": round(statistics.median(rest), 2),
            "p95_ms": round(rest[math.ceil(len(rest) * 0.95) - 1], 2), "max_ms": round(rest[-1], 2)}  # fmt: skip


@pytest.mark.parametrize("n", SIZES)
async def test_the_misses_due_query_at_scale(n, pg_url, owner_sessionmaker, dispatch_sessionmaker) -> None:
    t = await _seeded(owner_sessionmaker, n)
    try:
        for name, shape in SHAPES.items():
            await _shaped(owner_sessionmaker, pg_url, t, shape)
            plan = await _plan(pg_url)  # the first read since the shape was made
            assert plan["rows"] == (0 if shape is None else 10)
            RESULTS.append({"incarnations": n, "shape": name, "picked": plan["rows"], "plan": plan,
                            "call": await _timed(dispatch_sessionmaker)})  # fmt: skip
    finally:
        for table in ("schedule_intervals", "schedule_incarnations", "schedules"):
            await sql(owner_sessionmaker, f"delete from {table} where tenant_id = :t", t=t)
    out = os.environ.get("DEWPOINT_PROBE_OUT")
    if out:
        Path(out).write_text(json.dumps(RESULTS, indent=1))  # noqa: ASYNC240  # after each size: kept if a later fails
