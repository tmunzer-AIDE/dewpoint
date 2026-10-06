# SPDX-License-Identifier: Apache-2.0
"""Webhook ingress's load probe (engine 2b spec §8.3, §15; the owner's ruling 12 on the 2b-3b outline): what its
provisional limits are measured against, reproducible for the rate decision and production sign-off. Run by hand,
never in CI; each part is bounded (a minute or two) and runs on a disposable Postgres 16 container (testcontainers),
with synthetic data only. From `backend/`:

    PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.ingress_load <part>

- `cost`: an authenticated body's parsing, splitting and sealing, on ingress's event loop;
- `limiter`: the failure limiter's table at saturation, and what eviction makes of its limit;
- `candidates`: `event_candidates()`, which ranks the whole pending backlog, against its size;
- `ingress`: latency, throughput and memory of one `dewpoint ingress` process (uvicorn, a process of its own), and a
  rate bucket's behavior;
- `lock`: how long a match transaction holds its endpoint's row, and what that costs ingress on that endpoint;
- `drain`: events matched per second through the dispatcher's own loop (a cycle, then its sleep), at a fan-out of 1, 3
  and 5 bindings: the per-endpoint event rate's default stays below it;
- `buckets`: each rate bucket (an endpoint's events and bytes, a tenant's events and bytes) at its default, on its own;
- `quotas`: each pending and retained quota (events and bytes, an endpoint's and a tenant's) at its default, on its own;
- `tenant-drain`: one tenant's endpoints drained together by one dispatcher or two (processes of their own), with two
  tenants as the control: a tenant's default event rate stays below it.

Numbers depend on the machine; record them with it."""

import asyncio
import base64
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
import tracemalloc
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import replace
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
MIB = 1024 * 1024
ROLES = ("dewpoint_api", "dewpoint_ingress", "dewpoint_dispatch", "dewpoint_worker", "dewpoint_admin",
         "dewpoint_auditor")  # fmt: skip
FAST = {  # an endpoint whose buckets never refuse, for parts that measure something else
    "request_per_s": 1e6, "request_burst": 10**6, "request_tokens": 1e6, "event_per_s": 1e6, "event_burst": 10**7,
    "event_tokens": 1e7, "byte_per_s": 1e9, "byte_burst": 10**10, "byte_tokens": 1e10, "pending_events_max": 10**7,
    "retained_events_max": 10**7, "pending_bytes_max": 10**11, "retained_bytes_max": 10**11,
}  # fmt: skip


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))]


def ms(seconds: float) -> str:
    return f"{seconds * 1000:.2f} ms"


def cost() -> None:
    from dewpoint.apps.ingress.batch import prepare
    from dewpoint.apps.ingress.endpoints import Endpoint
    from dewpoint.core.crypto import events

    _, public = events.generate_keypair()
    base = Endpoint(id=uuid.uuid4(), tenant_id=uuid.uuid4(), enabled=True, tenant_active=True, auth_kind="bearer",
                    bearer_digest=b"", hmac_secret=None, signature_header=None, timestamp_header=None, tolerance_s=300,
                    allowlist=(), body_limit=5 * MIB, id_source="none", id_pointer=None, id_header=None,
                    events_pointer=None, dedupe_key=b"", key_version=1, public_key=public)  # fmt: skip
    batch = replace(base, id_source="pointer", id_pointer="/id", events_pointer="/events")
    secret = os.urandom(32)
    pads = lambda size: json.dumps({"events": [{"id": f"e-{i}", "pad": "x" * size} for i in range(500)]}).encode()  # noqa: E731
    cases: dict[str, tuple[Any, bytes, bytes | None]] = {
        "1 event, 1 KiB": (base, json.dumps({"type": "ap_down", "pad": "x" * 1000}).encode(), None),
        "500 events, ~1 MiB, ids": (batch, pads(2000), secret),
        "500 events, ~5 MiB, ids": (batch, pads(10400), secret),
        "1 event, 5 MiB string": (base, json.dumps({"pad": "x" * (5 * MIB - 20)}).encode(), None),
        "1 event, ~5 MiB of small integers": (base, json.dumps({"a": [0] * (5 * MIB // 3 - 10)}).encode(), None),
        "1 event, ~1.1 MiB of 1e15 (canonical x4.5)": (base, ('{"a":[' + ",".join(["1e15"] * 230_000) + "]}").encode(),
                                                       None),
    }  # fmt: skip
    print("| body | bytes | prepare (median) | MiB/s | peak memory |\n|---|---|---|---|---|")
    for name, (endpoint, body, key) in cases.items():
        times = []
        for _ in range(3 if len(body) > MIB else 20):
            start = time.perf_counter()
            prepare(endpoint, body, None, key)
            times.append(time.perf_counter() - start)
        tracemalloc.start()
        prepare(endpoint, body, None, key)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        median = statistics.median(times)
        print(f"| {name} | {len(body):,} | {ms(median)} | {len(body) / MIB / median:.1f} | {peak / MIB:.1f} MiB |")


def limiter() -> None:
    from dewpoint.apps.ingress.limits import FailureLimiter

    address = lambda prefix, i: f"{prefix}:{i // 65536:x}:{i % 65536:x}::/64"  # noqa: E731
    table = FailureLimiter(failures=30, window_s=60)
    tracemalloc.start()
    start = time.perf_counter()
    for i in range(65_536):
        table.fail(address("2001:db8", i), 0.0)
    filled = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    start = time.perf_counter()
    for i in range(100_000):
        table.fail(address("2001:db9", i), 1.0)
    full = time.perf_counter() - start
    print(f"fill 65,536 entries: {ms(filled)} ({filled / 65_536 * 1e6:.2f} us each); peak ~{peak / MIB:.1f} MiB")
    print(f"a failure on a full table (evicting): {full / 100_000 * 1e6:.2f} us")
    victim = FailureLimiter(failures=30, window_s=60)
    for _ in range(29):
        victim.fail("203.0.113.9", 0.0)
    for i in range(65_536):
        victim.fail(address("2001:dba", i), 1.0)
    for _ in range(29):
        victim.fail("203.0.113.9", 2.0)
    blocked = victim.blocked("203.0.113.9", 2.0) is not None
    print("29 failures, then 65,536 other /64s in the same minute: the address is evicted and fails 29 more "
          f"(blocked: {blocked}): best-effort past the table's size")  # fmt: skip


class Database:
    """A disposable Postgres 16, migrated, with the roles the tests use and a `development` deployment."""

    def __enter__(self) -> "Database":
        from testcontainers.community.postgres import PostgresContainer

        self._container = PostgresContainer("postgres:16-alpine", driver="asyncpg").__enter__()
        self.url = self._container.get_connection_url()
        env = {**os.environ, "DEWPOINT_DATABASE_URL": self.url, "UV_NO_SYNC": "1"}
        subprocess.run([".venv/bin/alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True)
        return self

    def __exit__(self, *exc: object) -> None:
        self._container.__exit__(*exc)

    def role_url(self, role: str) -> str:
        return f"postgresql+asyncpg://t_{role}:pw@{self.url.split('@', 1)[1]}"

    def sessions(self, role: str | None = None) -> Any:
        from dewpoint.core.db import make_engine, make_sessionmaker

        return make_sessionmaker(make_engine(self.role_url(role) if role else self.url))

    async def prepared(self) -> None:
        from sqlalchemy import text

        from dewpoint.core.db import make_engine, make_sessionmaker
        from dewpoint.core.platform.service import DEVELOPMENT, record_environment

        engine = make_engine(self.url)
        async with engine.begin() as c:
            for role in ROLES:
                await c.execute(text(f"CREATE ROLE t_{role} LOGIN PASSWORD 'pw' IN ROLE {role}"))
        async with make_sessionmaker(engine)() as s, s.begin():
            await record_environment(s, environment=DEVELOPMENT, namespace="default")
        await engine.dispose()


async def candidates(db: Database) -> None:
    from sqlalchemy import text

    from tests.core.ingress.support import endpoint

    owner, dispatch = db.sessions(), db.sessions("dewpoint_dispatch")
    endpoints = [await endpoint(owner) for _ in range(10)]
    total = 0
    print("| pending events (10 tenants) | event_candidates(50), median of 5 | max |\n|---|---|---|")
    for target in (1_000, 10_000, 50_000, 200_000):
        per_tenant = (target - total) // len(endpoints)
        async with owner() as s, s.begin():
            for tenant, endpoint_id in endpoints:
                await s.execute(text(
                    "insert into inbound_events (id, tenant_id, endpoint_id, key_version, sealed, size_bytes, "
                    "received_at) select gen_random_uuid(), :t, :e, 1, '\\x01', 1, now() - make_interval(secs => g) "
                    "from generate_series(1, :n) g"), {"t": tenant, "e": endpoint_id, "n": per_tenant})  # fmt: skip
            await s.execute(text("analyze inbound_events"))
        total += per_tenant * len(endpoints)
        times = []
        for _ in range(5):
            async with dispatch() as s:
                start = time.perf_counter()
                await s.execute(text("select * from event_candidates(50)"))
                times.append(time.perf_counter() - start)
        print(f"| {total:,} | {ms(statistics.median(times))} | {ms(max(times))} |")


async def ingress(db: Database) -> None:
    import httpx
    from sqlalchemy import text

    from tests.core.ingress.support import endpoint

    owner = db.sessions()
    token = "dwp_probe-token"  # noqa: S105 - the probe's own
    digest = hashlib.sha256(token.encode()).digest()
    tenant, fast = await endpoint(owner, bearer_digest=digest, **FAST)
    async with owner() as s, s.begin():
        await s.execute(text("insert into tenant_event_counters (tenant_id, event_per_s, event_burst, event_tokens, "
                             "byte_per_s, byte_burst, byte_tokens, pending_events_max, retained_events_max, "
                             "pending_bytes_max, retained_bytes_max) values (:t, 1e6, 10000000, 1e7, 1e9, 10000000000, "
                             "1e10, 10000000, 10000000, 100000000000, 100000000000)"), {"t": tenant})  # fmt: skip
    _, limited = await endpoint(owner, bearer_digest=digest)  # the defaults
    env = {k: v for k, v in os.environ.items() if not k.startswith("DEWPOINT_KEK")} | {
        "DEWPOINT_DATABASE_URL": db.role_url("dewpoint_ingress"), "PYTHONPATH": f"{BACKEND}/src",
        "DEWPOINT_INGRESS_KEY_B64": base64.b64encode(os.urandom(32)).decode(),
    }  # fmt: skip
    server = subprocess.Popen([".venv/bin/python", "-c", "from dewpoint.apps.cli.main import app; app()", "ingress",  # noqa: ASYNC220 - started once, before the measuring
                               "--port", "18099"], cwd=BACKEND, env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)  # fmt: skip

    def rss() -> float:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(server.pid)], capture_output=True, text=True).stdout
        return int(out.strip() or 0) / 1024

    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18099", timeout=30,
                                     limits=httpx.Limits(max_connections=64)) as c:  # fmt: skip
            for _ in range(100):
                try:
                    if (await c.get("/health/ready")).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            headers = {"authorization": f"Bearer {token}"}
            body = json.dumps({"type": "ap_down", "pad": "x" * 1000}).encode()
            print(f"ingress RSS idle: {rss():.0f} MiB")
            print("| concurrency | requests | throughput | p50 | p95 | p99 | RSS |\n|---|---|---|---|---|---|---|")

            async def one(n: int, latencies: list[float]) -> None:
                for _ in range(n):
                    start = time.perf_counter()
                    answer = await c.post(f"/hooks/{fast}", content=body, headers=headers)
                    latencies.append(time.perf_counter() - start)
                    assert answer.status_code == 200, answer.text

            for concurrency in (1, 8, 32):
                latencies: list[float] = []
                start = time.perf_counter()
                await asyncio.gather(*(one(400 // concurrency, latencies) for _ in range(concurrency)))
                elapsed = time.perf_counter() - start
                print(f"| {concurrency} | {len(latencies)} | {len(latencies) / elapsed:.0f}/s | "
                      f"{ms(pct(latencies, .5))} | {ms(pct(latencies, .95))} | {ms(pct(latencies, .99))} | "
                      f"{rss():.0f} MiB |")  # fmt: skip
            statuses: list[int] = []
            start = time.perf_counter()

            async def hammer() -> None:
                for _ in range(40):
                    answer = await c.post(f"/hooks/{limited}", content=b'{"n": 1}', headers=headers)
                    statuses.append(answer.status_code)

            await asyncio.gather(*(hammer() for _ in range(8)))
            elapsed = time.perf_counter() - start
            print(
                f"the default request bucket (20/s, burst 100): 320 requests in {elapsed:.2f} s, "
                f"{statuses.count(200)} accepted, {statuses.count(429)} refused; it allows {100 + 20 * elapsed:.0f}"
            )
    finally:
        server.terminate()
        server.wait(10)


def _settings(db: Database) -> Any:
    from dewpoint.core.config import Settings

    return Settings(database_url=db.role_url("dewpoint_api"), kek_b64=base64.b64encode(b"k" * 32).decode(),
                    public_origin="https://probe", rp_id="probe")  # fmt: skip


async def _inbound(db: Database, fan_out: int) -> Any:
    """A tenant with `fan_out` published workflows, all bound to one endpoint whose buckets never refuse."""
    from sqlalchemy import text

    from tests.apps.dispatcher.inbound import bind, inbound
    from tests.apps.test_admission import OPEN_GRAPH
    from tests.apps.test_workflow_ops import create, publish

    owner, api = db.sessions(), db.sessions("dewpoint_api")
    settings = _settings(db)
    ready = await inbound(owner, api, db.sessions("dewpoint_admin"), db.sessions("dewpoint_dispatch"), settings)
    await bind(owner, ready)
    for n in range(fan_out - 1):
        workflow = await create(api, ready.ctx, OPEN_GRAPH, name=f"fan-{n}")
        assert (await publish(api, ready.ctx, workflow, settings)).version is not None
        await bind(owner, ready, workflow)
    async with owner() as s, s.begin():
        await s.execute(text("update webhook_endpoints set " + ", ".join(f"{k} = :{k}" for k in FAST)  # noqa: S608
                             + " where id = :e"), FAST | {"e": ready.endpoint_id})  # fmt: skip
        await s.execute(text("insert into tenant_event_counters (tenant_id, event_per_s, event_burst, event_tokens, "
                             "byte_per_s, byte_burst, byte_tokens) values (:t, 1e6, 10000000, 1e7, 1e9, 10000000000, "
                             "1e10) on conflict (tenant_id) do update set event_per_s = 1e6, event_burst = 10000000, "
                             "event_tokens = 1e7, byte_per_s = 1e9, byte_burst = 10000000000, byte_tokens = 1e10"),
                        {"t": ready.tenant_id})  # fmt: skip
    return ready


async def _record(db: Database, ready: Any, n: int, *, batch: int = 1) -> list[float]:
    """`n` events recorded through ingress's function, `batch` a call: each call's time."""
    from tests.apps.dispatcher.inbound import sealed
    from tests.core.ingress.support import RECORD

    ingress_ = db.sessions("dewpoint_ingress")
    times = []
    for _ in range(n // batch):
        ids = [uuid.uuid4() for _ in range(batch)]
        params = {"e": ready.endpoint_id, "refusal": None, "read": 0, "ids": ids,
                  "sealed": [sealed(ready, i, {"type": "ap_down", "pad": "x" * 500}) for i in ids],
                  "versions": [1] * batch, "dedupe": [None] * batch, "digests": [None] * batch}  # fmt: skip
        start = time.perf_counter()
        async with ingress_() as s, s.begin():
            await s.execute(RECORD, params)
        times.append(time.perf_counter() - start)
    return times


async def lock(db: Database) -> None:
    from sqlalchemy import text

    from dewpoint.apps.dispatcher import matching
    from tests.apps.test_admission import KEYS

    ready = await _inbound(db, 1)
    dispatch = db.sessions("dewpoint_dispatch")
    idle = await _record(db, ready, 300)
    print(f"recording on an idle endpoint: p50 {ms(pct(idle, 0.5))}, p95 {ms(pct(idle, 0.95))}")
    await _record(db, ready, 200)
    async with dispatch() as s:
        picked = (await s.execute(text("select tenant_id, event_id, endpoint_id from event_candidates(200)"))).all()
    verified, held = matching.Verified(), []
    for tenant_id, event_id, endpoint_id in picked:
        start = time.perf_counter()
        await matching.match_event(dispatch, KEYS, verified, tenant_id=tenant_id, event_id=event_id,
                                   endpoint_id=endpoint_id)  # fmt: skip
        held.append(time.perf_counter() - start)
    print(f"a match transaction, which holds its endpoint's row (an upper bound): p50 {ms(pct(held, .5))}, "
          f"p95 {ms(pct(held, .95))}, max {ms(max(held))}")  # fmt: skip
    await _record(db, ready, 1000)

    async def matched_without_pause() -> None:  # the endpoint's row held as much as matching can
        while await matching.match_once(dispatch, KEYS, verified):
            pass

    task = asyncio.create_task(matched_without_pause())
    contended = await _record(db, ready, 300)
    await task
    print(f"recording while that endpoint is matched back to back: p50 {ms(pct(contended, .5))}, "
          f"p95 {ms(pct(contended, .95))}, max {ms(max(contended))}")  # fmt: skip


async def drain(db: Database) -> None:
    """Events matched per second through `dewpoint dispatcher`'s own loop: `main.cycle` (it observes the build,
    dispatches what's due, then matches), then the loop's `CYCLE_S` sleep, one dispatcher, not the leader (whose
    reconciling only adds to a cycle). Temporal is a fake that accepts each start at once, so a real one's latency only
    lowers this."""
    from tests.apps.dispatcher.support import workers

    owner, dispatch, settings = db.sessions(), db.sessions("dewpoint_dispatch"), _settings(db)
    await workers(owner)

    class NotLeading:
        async def leading(self) -> bool:
            return False

    print("| fan-out | events | elapsed | events/s sustained | requests admitted | cycle time, median |")
    print("|---|---|---|---|---|---|")
    for fan_out in (1, 3, 5):
        ready = await _inbound(db, fan_out)
        await _record(db, ready, 500, batch=100)
        await _drained(owner, dispatch, settings, ready, fan_out, 500, NotLeading())


async def _drained(owner: Any, dispatch: Any, settings: Any, ready: Any, fan_out: int, events: int,
                   leader: Any) -> None:  # fmt: skip
    """The endpoint's pending events drained through the dispatcher's loop, timed, and a row printed."""
    from sqlalchemy import text

    from dewpoint.apps.dispatcher import dispatch as dispatching
    from dewpoint.apps.dispatcher import main
    from tests.apps.test_admission import KEYS
    from tests.apps.test_runs import FakeClient

    client, rotation, verified = FakeClient(), dispatching.Rotation(), main.Verified()
    cycles: list[float] = []

    async def one() -> None:
        start = time.perf_counter()
        await main.cycle(dispatch, client, KEYS, settings, instance=uuid.uuid4(), reconciler=uuid.uuid4(),  # type: ignore[arg-type]
                         leader=leader, rotation=rotation, verified=verified)  # fmt: skip
        cycles.append(time.perf_counter() - start)

    query = text("select count(*) from inbound_events where endpoint_id = :e and status = 'pending'")
    start = time.perf_counter()
    while True:
        async with owner() as s:
            if not (await s.execute(query, {"e": ready.endpoint_id})).scalar_one():
                break
        await main.serve(one, cycles=1)  # a cycle, then the loop's own sleep
    elapsed = time.perf_counter() - start
    admitted_query = text("select count(*) from run_requests where idempotency_key like 'evt:%' and workflow_id in "
                          "(select workflow_id from trigger_bindings where endpoint_id = :e)")  # fmt: skip
    async with owner() as s:
        admitted = (await s.execute(admitted_query, {"e": ready.endpoint_id})).scalar_one()
    print(f"| {fan_out} | {events} | {elapsed:.1f} s | {events / elapsed:.1f} | {admitted} | "
          f"{ms(statistics.median(cycles))} |")  # fmt: skip


# Each limit measured on its own (the owner's M4 review): a fresh tenant and endpoint for each, every other limit
# relaxed, the one measured at its default, through `record_inbound_events` itself.
TENANT_FAST = {
    "event_per_s": 1e6, "event_burst": 10**7, "event_tokens": 1e7, "byte_per_s": 1e9, "byte_burst": 10**10,
    "byte_tokens": 1e10, "pending_events_max": 10**7, "pending_bytes_max": 10**11, "retained_events_max": 10**7,
    "retained_bytes_max": 10**11,
}  # fmt: skip
ENDPOINT_FAST = FAST | {"body_limit": 5 * MIB, "byte_burst": 10**10}


async def _measured(db: Database, endpoint_limits: tuple[str, ...], tenant_limits: tuple[str, ...]) -> uuid.UUID:
    """A fresh endpoint whose limits are relaxed but those named (left at their defaults), of a fresh tenant
    likewise."""
    from sqlalchemy import text

    from tests.core.ingress.support import endpoint

    owner = db.sessions()
    columns = {k: v for k, v in ENDPOINT_FAST.items() if not any(k.startswith(limit) for limit in endpoint_limits)}
    tenant, endpoint_id = await endpoint(owner, **columns)
    relaxed = {k: v for k, v in TENANT_FAST.items() if not any(k.startswith(limit) for limit in tenant_limits)}
    async with owner() as s, s.begin():
        await s.execute(text(f"insert into tenant_event_counters (tenant_id, {', '.join(relaxed)}) values "  # noqa: S608
                             f"(:t, {', '.join(':' + k for k in relaxed)})"), {"t": tenant} | relaxed)  # fmt: skip
    return endpoint_id


async def _call(
    ingress_: Any, endpoint_id: uuid.UUID, events: int, size: int, keyed: bool = False
) -> tuple[Any, float]:
    """One recording of `events` events of `size` sealed bytes each (keyed: with dedupe keys): its outcome and time."""
    from tests.core.ingress.support import RECORD, sealed_layout

    ids = [uuid.uuid4() for _ in range(events)]
    keys = [os.urandom(32) if keyed else None for _ in ids]
    sealed = [sealed_layout(os.urandom(size), 1) for _ in ids]  # the recording function stores no other layout
    params = {"e": endpoint_id, "refusal": None, "read": 0, "ids": ids, "sealed": sealed,
              "versions": [1] * events, "dedupe": keys, "digests": [k and os.urandom(32) for k in keys]}  # fmt: skip
    start = time.perf_counter()
    async with ingress_() as s, s.begin():
        outcome = dict((await s.execute(RECORD, params)).scalar_one())
    return outcome | {"params": params}, time.perf_counter() - start


async def buckets(db: Database) -> None:
    """Each rate bucket at its default, sent to as fast as one caller can for 3 s: what it accepted against what it
    allows (its burst, and its rate over the time taken), and the wait a refusal names."""
    ingress_ = db.sessions("dewpoint_ingress")
    cases = (  # (bucket, endpoint limits kept, tenant limits kept, events a call, bytes an event, unit, burst, rate)
        ("endpoint events (10/s, burst 1,000)", ("event_",), (), 1, 100, "events", 1000, 10),
        ("endpoint bytes (2 MiB/s, burst 10 MiB)", ("byte_", "body_limit"), (), 1, MIB // 2,
         "bytes", 10 * MIB, 2 * MIB),
        ("tenant events (10/s, burst 5,000)", (), ("event_",), 100, 100, "events", 5000, 10),
        ("tenant bytes (10 MiB/s, burst 50 MiB)", (), ("byte_",), 1, 4 * MIB, "bytes", 50 * MIB, 10 * MIB),
    )  # fmt: skip
    print("| bucket | accepted | it allows | refused calls | a refusal's Retry-After | a call, median |")
    print("|---|---|---|---|---|---|")
    for name, kept_endpoint, kept_tenant, events, size, unit, burst, rate in cases:
        endpoint_id = await _measured(db, kept_endpoint, kept_tenant)
        accepted, refused, waits, times = 0, 0, [], []
        start = time.perf_counter()
        while time.perf_counter() - start < 3:
            outcome, took = await _call(ingress_, endpoint_id, events, size)
            times.append(took)
            if outcome["outcome"] == "recorded":
                accepted += events * (1 if unit == "events" else size)
            else:
                refused += 1
                waits.append(outcome.get("retry_after"))
        elapsed = time.perf_counter() - start
        shown = (lambda v: f"{v:,}") if unit == "events" else (lambda v: f"{v / MIB:.1f} MiB")  # noqa: E731
        print(f"| {name} | {shown(accepted)} | {shown(int(burst + rate * elapsed))} | {refused} | "
              f"{sorted(set(waits))[:3]} | {ms(statistics.median(times))} |")  # fmt: skip


async def quotas(db: Database) -> None:
    """Each pending and retained quota at its default, filled until refused: what it took, the refusal, a duplicate's
    acknowledgment at the quota, and a call's time empty and full."""
    ingress_ = db.sessions("dewpoint_ingress")
    pending, retained = ("pending_",), ("retained_",)
    cases = (  # (quota, endpoint limits kept, tenant limits kept, events a call, bytes an event)
        ("endpoint pending events (10,000)", pending, (), 500, 64),
        ("endpoint pending bytes (64 MiB)", pending, (), 1, 4 * MIB),
        ("tenant pending events (50,000)", (), pending, 500, 64),
        ("tenant pending bytes (256 MiB)", (), pending, 1, 4 * MIB),
        ("endpoint retained events (100,000)", retained, (), 500, 64),
        ("endpoint retained bytes (512 MiB)", retained, (), 1, 4 * MIB),
        ("tenant retained events (250,000)", (), retained, 500, 64),
        ("tenant retained bytes (1 GiB)", (), retained, 1, 4 * MIB),
    )
    print("| quota | taken before refusal | refusal | Retry-After | a duplicate at it | a call, first / last |")
    print("|---|---|---|---|---|---|")
    for name, kept_endpoint, kept_tenant, events, size in cases:
        endpoint_id = await _measured(db, kept_endpoint, kept_tenant)
        taken, first, times = 0, None, []
        while True:
            outcome, took = await _call(ingress_, endpoint_id, events, size, keyed=True)
            times.append(took)
            if outcome["outcome"] != "recorded":
                break
            first = first or outcome["params"]
            taken += events
        from tests.core.ingress.support import RECORD

        again = {**first, "ids": [uuid.uuid4() for _ in first["ids"]]}  # the first call's events, a sender's retry
        async with ingress_() as s, s.begin():
            duplicate = dict((await s.execute(RECORD, again)).scalar_one())
        amount = f"{taken:,} events" if size < 1024 else f"{taken * size / MIB:.0f} MiB"
        print(f"| {name} | {amount} | {outcome['outcome']} | {outcome.get('retry_after', 'none')} | "
              f"{duplicate.get('duplicates', duplicate['outcome'])} acknowledged | "
              f"{ms(statistics.median(times[:5]))} / {ms(statistics.median(times[-5:]))} |")  # fmt: skip


async def tenant_drain(db: Database) -> None:
    """One tenant's endpoints drained together, by one dispatcher or two (each a process of its own, its own loop):
    every match holds the tenant's counter row, so a tenant's endpoints are matched one at a time whatever the
    dispatchers. Two tenants by two dispatchers is the control. Fan-out 1; a fake Temporal, as `drain`."""
    from tests.apps.dispatcher.inbound import bind, endpoint
    from tests.apps.dispatcher.support import workers

    owner = db.sessions()
    await workers(owner)
    scenarios = (  # (name, tenants, endpoints a tenant, dispatchers)
        ("1 tenant, 1 endpoint, 1 dispatcher", 1, 1, 1),
        ("1 tenant, 4 endpoints, 1 dispatcher", 1, 4, 1),
        ("1 tenant, 4 endpoints, 2 dispatchers", 1, 4, 2),
        ("2 tenants, 2 endpoints each, 2 dispatchers (control)", 2, 2, 2),
    )
    print("| scenario | events | elapsed | events/s sustained |\n|---|---|---|---|")
    for name, tenants, per_tenant, dispatchers in scenarios:
        total = 400
        for _ in range(tenants):
            ready = await _inbound(db, 1)
            endpoints = [ready.endpoint_id]
            for _ in range(per_tenant - 1):
                extra = await endpoint(owner, ready.tenant_id, ready.user_id, **FAST)
                await bind(owner, ready, endpoint_id=extra)
                endpoints.append(extra)
            for endpoint_id in endpoints:
                await _record(db, replace_endpoint(ready, endpoint_id), total // (tenants * per_tenant), batch=50)
        env = os.environ | {"PYTHONPATH": f"{BACKEND}/src:{BACKEND}"}
        children = [subprocess.Popen([".venv/bin/python", "-m", "tests.probes.ingress_load", "dispatcher-loop",  # noqa: ASYNC220
                                      db.role_url("dewpoint_dispatch")], cwd=BACKEND, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                    for _ in range(dispatchers)]  # fmt: skip
        spans = [tuple(float(v) for v in child.communicate()[0].split()[-2:]) for child in children]
        elapsed = max(end for _, end in spans) - min(begin for begin, _ in spans)
        print(f"| {name} | {total} | {elapsed:.1f} s | {total / elapsed:.1f} |")


def replace_endpoint(ready: Any, endpoint_id: uuid.UUID) -> Any:
    return replace(ready, endpoint_id=endpoint_id)


async def dispatcher_loop(dispatch_url: str) -> None:
    """A dispatcher of `tenant-drain`'s, in a process of its own: its loop until nothing is pending, then the times its
    first cycle began and its last ended."""
    from sqlalchemy import text

    from dewpoint.apps.dispatcher import dispatch as dispatching
    from dewpoint.apps.dispatcher import main
    from dewpoint.core.config import Settings
    from dewpoint.core.db import make_engine, make_sessionmaker
    from tests.apps.test_admission import KEYS
    from tests.apps.test_runs import FakeClient

    class NotLeading:
        async def leading(self) -> bool:
            return False

    sessions = make_sessionmaker(make_engine(dispatch_url))
    settings = Settings(database_url=dispatch_url, kek_b64=base64.b64encode(b"k" * 32).decode(),
                        public_origin="https://probe", rp_id="probe")  # fmt: skip
    client, rotation, verified = FakeClient(), dispatching.Rotation(), main.Verified()

    async def one() -> None:
        await main.cycle(sessions, client, KEYS, settings, instance=uuid.uuid4(), reconciler=uuid.uuid4(),  # type: ignore[arg-type]
                         leader=NotLeading(), rotation=rotation, verified=verified)  # fmt: skip

    begin = time.time()
    while True:
        async with sessions() as s:
            if not (await s.execute(text("select 1 from event_candidates(1)"))).first():
                break
        await main.serve(one, cycles=1)
    print(begin, time.time())


PARTS: dict[str, Callable[[Database], Coroutine[Any, Any, None]]] = {
    "candidates": candidates, "ingress": ingress, "lock": lock, "drain": drain, "buckets": buckets, "quotas": quotas,
    "tenant-drain": tenant_drain,
}  # fmt: skip


def run(part: str, *args: str) -> None:
    if part == "dispatcher-loop":  # a child of `tenant-drain`
        asyncio.run(dispatcher_loop(args[0]))
    elif part == "cost":
        cost()
    elif part == "limiter":
        limiter()
    else:
        with Database() as db:

            async def go() -> None:
                await db.prepared()
                await PARTS[part](db)

            asyncio.run(go())


if __name__ == "__main__":
    run(*sys.argv[1:])
