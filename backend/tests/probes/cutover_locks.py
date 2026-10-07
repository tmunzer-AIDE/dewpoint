# SPDX-License-Identifier: Apache-2.0
"""The schedule inventory's cutover under load (the owner's review of the 2b-4b M1 checkpoint 3: measure concurrent
writers through the cutover). A database at the head, its cutover not recorded, as an online upgrade leaves it, seeded
with `schedules` schedules, `PER_TENANT` a tenant: each captured as the old application's were (its incarnation 0, its
life before unknown), but a share the capture missed (`MISSED`, added with it off), and a share whose counts the old
dispatcher recorded since (`RECOUNTED`). Schedules' writers and readers run throughout (`Writers`: an API's insert of a
schedule, an update, a read of a schedule's incarnations, a tenant's list), `per_kind` connections a kind, one
operation at a time with `pause` seconds between them; then the cutover, as `dewpoint schedules inventory-cutover
--confirm` runs it (`dewpoint.core.platform.inventory`): its catch-up in batches, then its final step. Each operation's
time is kept; accepted when the cutover is recorded, every schedule from before it is accounted for, no operation
failed and none waited `ACCEPT_S`. A run by hand, never in CI:

    PYTHONPATH=src:. .venv/bin/python -m tests.probes.cutover_locks 100000 --out cutover.json [--per-kind 4 --pause 0]
"""

import argparse
import asyncio
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import asyncpg
from testcontainers.community.postgres import PostgresContainer

from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.platform import inventory

BACKEND = Path(__file__).resolve().parents[2]
ACCEPT_S = 5.0  # D15: the most an operation may wait in total
PAUSE = 0.01  # seconds between one connection's operations
PER_TENANT = 1_000  # schedules a tenant
MISSED = 0.01  # the share of schedules the capture missed
RECOUNTED = 0.1  # the share whose counts the old dispatcher recorded after the capture copied them
SCHEDULE = (
    "INSERT INTO schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by, generation, "
    "synced_generation, misses) SELECT gen_random_uuid(), w.tenant_id, w.id, 60, 'live', '\\x01'::bytea, $1, 2, 2, 1 "
    "FROM workflows w, generate_series(1, $2) g"
)


async def seed(url: str, schedules: int) -> dict[str, int]:
    """The schedules, as above; what was seeded, counted."""
    tenants = max(1, schedules // PER_TENANT)
    missed = int(PER_TENANT * MISSED)
    c = await asyncpg.connect(url)
    try:
        await c.execute("INSERT INTO tenants (id, name, slug) SELECT gen_random_uuid(), 'T' || g, 'cut-' || g "
                        "FROM generate_series(1, $1) g", tenants)  # fmt: skip
        user = await c.fetchval("INSERT INTO users (id, email, password_hash) VALUES (gen_random_uuid(), "
                                "'cut@seed.test', 'x') RETURNING id")  # fmt: skip
        await c.execute("INSERT INTO workflows (id, tenant_id, name, enabled, draft) SELECT gen_random_uuid(), id, "
                        "'W', true, '{}' FROM tenants")  # fmt: skip
        await c.execute(SCHEDULE, user, PER_TENANT - missed)  # captured, as the old application's were
        async with c.transaction():  # the capture off, as only the table's owner could turn it
            await c.execute("ALTER TABLE schedules DISABLE TRIGGER schedules_inventoried")
            await c.execute(SCHEDULE, user, missed)
            await c.execute("ALTER TABLE schedules ENABLE TRIGGER schedules_inventoried")
        await c.execute("UPDATE schedules SET misses = 3 WHERE random() < $1", RECOUNTED)  # the old dispatcher's
        await c.execute("ANALYZE")
        return {
            "schedules": await c.fetchval("SELECT count(*) FROM schedules"),
            "missed": await c.fetchval(
                "SELECT count(*) FROM schedules s WHERE NOT EXISTS (SELECT 1 FROM "
                "schedule_incarnations i WHERE i.schedule_id = s.id)"
            ),  # fmt: skip
            "recounted": await c.fetchval(
                "SELECT count(*) FROM schedules s JOIN schedule_incarnations i ON "
                "i.schedule_id = s.id WHERE s.misses > i.misses"
            ),  # fmt: skip
            "tenants": tenants,
        }
    finally:
        await c.close()


class Writers:
    """Schedules' writers and readers, as above, each operation's time kept (when it began, how long it took)."""

    KINDS = ("create_schedule", "update_schedule", "read_incarnations", "list_schedules")

    def __init__(self, url: str, per_kind: int, pause: float) -> None:
        self.url, self.per_kind, self.pause, self.stop = url, per_kind, pause, asyncio.Event()
        self.times: dict[str, list[tuple[float, float]]] = {k: [] for k in self.KINDS}
        self.errors: dict[str, dict[str, int]] = {k: {} for k in self.KINDS}
        self.ids: dict[str, list[Any]] = {}

    async def prepare(self) -> None:
        c = await asyncpg.connect(self.url)
        try:
            self.ids["schedules"] = list(await c.fetch("SELECT id, tenant_id, workflow_id, created_by FROM schedules "
                                                       "ORDER BY random() LIMIT 5000"))  # fmt: skip
        finally:
            await c.close()

    async def _op(self, c: asyncpg.Connection, kind: str) -> None:
        one = random.choice(self.ids["schedules"])  # noqa: S311  # synthetic load, no security meaning
        if kind == "create_schedule":
            await c.execute("INSERT INTO schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by) "
                            "VALUES (gen_random_uuid(), $1, $2, 60, 'live', '\\x01'::bytea, $3)",
                            one["tenant_id"], one["workflow_id"], one["created_by"])  # fmt: skip
        elif kind == "update_schedule":
            await c.execute("UPDATE schedules SET enabled = NOT enabled, updated_at = now() WHERE id = $1", one["id"])
        elif kind == "read_incarnations":
            await c.fetch("SELECT temporal_id, misses FROM schedule_incarnations WHERE schedule_id = $1 "
                          "ORDER BY number", one["id"])  # fmt: skip
        elif kind == "list_schedules":
            await c.fetch("SELECT id FROM schedules WHERE tenant_id = $1 ORDER BY created_at DESC LIMIT 50",
                          one["tenant_id"])  # fmt: skip

    async def loop(self, kind: str) -> None:
        c = await asyncpg.connect(self.url)
        try:
            while not self.stop.is_set():
                t0 = time.monotonic()
                try:
                    await self._op(c, kind)
                except asyncpg.PostgresError as e:  # counted by type, never by value; the loop carries on
                    self.errors[kind][type(e).__name__] = self.errors[kind].get(type(e).__name__, 0) + 1
                self.times[kind].append((t0, time.monotonic() - t0))
                await asyncio.sleep(self.pause)
        finally:
            await c.close()


async def measure(url: str, *, per_kind: int, pause: float) -> dict[str, Any]:
    writers = Writers(url, per_kind, pause)
    await writers.prepare()
    loops = [asyncio.create_task(writers.loop(k)) for k in Writers.KINDS for _ in range(per_kind)]
    await asyncio.sleep(2)  # the load's baseline, before the cutover
    baseline = {k: statistics.median(d for _, d in v) for k, v in writers.times.items() if v}
    engine = make_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        async with make_sessionmaker(engine)() as s:
            t0 = time.monotonic()
            caught = await inventory.catch_up(s)
            t1 = time.monotonic()
            at = await inventory.record(s, {"caught_up": caught.caught, "refreshed": caught.refreshed,
                                            "attested": "the cutover probe"})  # fmt: skip
            t2 = time.monotonic()
    finally:
        await engine.dispose()
    await asyncio.sleep(1)
    writers.stop.set()
    await asyncio.gather(*loops)
    c = await asyncpg.connect(url)
    try:
        unaccounted = await c.fetchval(
            "SELECT count(*) FROM schedules s WHERE s.created_at < (SELECT at FROM schedule_inventory_cutover) - "
            "interval '1 second' AND NOT EXISTS (SELECT 1 FROM schedule_incarnations i WHERE i.schedule_id = s.id "
            "AND i.number = 0 AND i.misses >= s.misses)"
        )  # fmt: skip
    finally:
        await c.close()
    during = {k: [d for began, d in v if t0 - 0.5 <= began <= t2 + 0.5] for k, v in writers.times.items()}
    return {
        "recorded": at is not None,
        "catch_up": {"seconds": round(t1 - t0, 3), "batches": caught.batches, "caught": caught.caught,
                     "refreshed": caught.refreshed},
        "final_step_s": round(t2 - t1, 4),
        "unaccounted": unaccounted,
        "load": {k: {"ops": len(v), "baseline_ms": round(baseline.get(k, 0) * 1000, 2),
                     "max_wait_s": round(max(v, default=0), 3), "over_5s": sum(d > ACCEPT_S for d in v)}
                 for k, v in during.items()},
        "errors": {k: v for k, v in writers.errors.items() if v},
    }  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("schedules", type=int)
    parser.add_argument("--out")
    parser.add_argument("--per-kind", type=int, default=1, help="connections per kind of operation (a heavier load)")
    parser.add_argument("--pause", type=float, default=PAUSE, help="seconds between a connection's operations")
    args = parser.parse_args()
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        url = pg.get_connection_url()
        env = {**os.environ, "DEWPOINT_DATABASE_URL": url.replace("postgresql://", "postgresql+asyncpg://")}
        subprocess.run([str(BACKEND / ".venv/bin/alembic"), "upgrade", "head"], cwd=BACKEND, env=env,  # noqa: S603
                       check=True, capture_output=True)  # fmt: skip
        t = time.monotonic()
        seeded = asyncio.run(seed(url, args.schedules))
        seed_s = round(time.monotonic() - t, 1)
        result = asyncio.run(measure(url, per_kind=args.per_kind, pause=args.pause))
    accepted = (result["recorded"] and result["unaccounted"] == 0 and not result["errors"]
                and all(v["over_5s"] == 0 for v in result["load"].values()))  # fmt: skip
    out = {"schedules": args.schedules, "writers": {"per_kind": args.per_kind, "pause": args.pause}, "seeded": seeded,
           "seed_s": seed_s, "batch": inventory.CATCH_UP_BATCH, "accepted": accepted,
           "machine": {"platform": platform.platform(), "cpus": os.cpu_count(), "python": sys.version.split()[0]},
           **result}  # fmt: skip
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=1, default=str))
    summary = {k: out[k] for k in ("schedules", "writers", "seeded", "accepted", "catch_up", "final_step_s",
                                   "unaccounted", "errors")}  # fmt: skip
    summary["max_wait_s"] = max(v["max_wait_s"] for v in out["load"].values())
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
