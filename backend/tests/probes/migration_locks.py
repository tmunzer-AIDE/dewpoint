# SPDX-License-Identifier: Apache-2.0
"""The large-table migration locks' probe (the 2b-4b plan's M1a; the owner's D15): how long upgrading a populated
database to the head holds each table, and what that costs normal readers and writers meanwhile. Run by hand, never in
CI; each run is bounded and uses a disposable Postgres 16 container (testcontainers), with synthetic data only. From
`backend/`:

    PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.migration_locks <from> <roots> [--out FILE]

`<from>` is the starting revision (`0034` or `0042`, D15's two paths) and `<roots>` the root runs seeded there, the rest
in proportion (`PROFILE`). The seeded database is copied twice, and `alembic upgrade head` runs on each copy in one
transaction, as a deployment's would:
- **control**, alone: a sampler reads the migrating backend's relation locks and statement every `SAMPLE` seconds, so
  each existing table's reads and writes are blocked from when the upgrade first took such a lock to its commit
  (`held`): what a normal operation arriving then would wait;
- **loaded**, under a synthetic normal load, one operation at a time per kind (`Load.KINDS`: an API's reads, a worker's
  projections, an admission, an ingress recording), each operation's time kept, and whether the upgrade completes.
D15's acceptance: no operation waits more than five seconds in total during the upgrade. Numbers depend on the
machine; record them with it."""

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
import uuid
from pathlib import Path
from typing import Any

import asyncpg
from testcontainers.community.postgres import PostgresContainer

BACKEND = Path(__file__).resolve().parents[2]
CEL = "cel-cpp-0.1.3/fn-1/cls-1"
SAMPLE = 0.1  # seconds between the sampler's reads of the migrating backend
ACCEPT_S = 5.0  # D15: the most an operation may wait in total during the upgrade
PAUSE = 0.05  # seconds between one kind's operations
BLOB = b"\x00" * 16
DIGEST = b"\x00" * 32  # a request's digest: 32 bytes

# Per root run: 0.5 sub-runs (every fourth root has two), 4 steps a run, an envelope and a claim (`run_inputs`), 2
# outputs a run (`step_outputs`), a grant a sub-run, a secret index, a request and an event. Per tenant (a thousand
# roots each, at least ten tenants): 3 members, 5 workflows of 2 versions, 3 connections, 2 schedules, an endpoint and
# its binding, a mapping, a data key, an event key and a counter row.
PROFILE = {"roots_per_tenant": 1_000, "min_tenants": 10, "subrun_every": 4, "subruns": 2, "steps_per_run": 4,
           "outputs_per_run": 2, "workflows": 5, "versions": 2, "connections": 3, "schedules": 2,
           "members": 3}  # fmt: skip

SEED = [
    "INSERT INTO cel_profiles (profile) VALUES ($1) ON CONFLICT DO NOTHING",
    "INSERT INTO tenants (id, name, slug) SELECT gen_random_uuid(), 'T' || g, 'seed-' || g "
    "FROM generate_series(1, $1) g",
    "CREATE TEMP TABLE t AS SELECT id, row_number() OVER (ORDER BY id) n FROM tenants",
    "INSERT INTO users (id, email, password_hash) SELECT gen_random_uuid(), 'u' || g || '@seed.test', 'x' "
    "FROM generate_series(1, $1) g",
    "CREATE TEMP TABLE u AS SELECT id, row_number() OVER (ORDER BY id) n FROM users",
    "INSERT INTO memberships (tenant_id, user_id, role) SELECT t.id, u.id, 'owner' FROM t JOIN u "
    "ON u.n BETWEEN (t.n - 1) * $1 + 1 AND t.n * $1",
    "CREATE TEMP TABLE tu AS SELECT t.id tid, min(u.id::text)::uuid uid FROM t JOIN u "
    "ON u.n BETWEEN (t.n - 1) * $1 + 1 AND t.n * $1 GROUP BY t.id",
    "INSERT INTO workflows (id, tenant_id, name, enabled, draft) SELECT gen_random_uuid(), t.id, 'W' || k, true, '{}' "
    "FROM t, generate_series(1, $1) k",
    "INSERT INTO workflow_versions (id, tenant_id, workflow_id, number, graph, node_refs, engine_abi, cel_profile, "
    "input_schema, output_schema, vars_schema, closure_version_ids, closure_workflow_ids, closure_node_refs, "
    "closure_cel_profiles, closure_depth, graph_hash, version_hash) "
    "SELECT vid, tid, wid, n, '{}', ARRAY['testkit.echo@1'], 1, $2::text, '{}', '{}', '{}', ARRAY[vid], ARRAY[wid], "
    "ARRAY['testkit.echo@1'], ARRAY[$2::text], 0, 'g', 'v' FROM (SELECT gen_random_uuid() vid, w.tenant_id tid, "
    "w.id wid, n FROM workflows w, generate_series(1, $1) n) x",
    "UPDATE workflows wf SET active_version_id = v.id FROM workflow_versions v WHERE v.workflow_id = wf.id "
    "AND v.number = $1",
    "CREATE TEMP TABLE tw AS SELECT v.id vid, v.workflow_id wid, v.tenant_id tid, row_number() OVER (ORDER BY v.id) n "
    "FROM workflow_versions v WHERE v.number = $1",
    "CREATE TEMP TABLE r AS SELECT gen_random_uuid() id, g n FROM generate_series(1, $1) g",
    "CREATE TEMP TABLE rr AS SELECT r.id, r.n, tw.vid, tw.wid, tw.tid, gen_random_uuid() env FROM r JOIN tw "
    "ON tw.n = ((r.n - 1) % (SELECT count(*) FROM tw)) + 1",
    "INSERT INTO run_inputs (id, tenant_id, owner_run_id, root_run_id, sensitive_pointers, ciphertext, role, pointer) "
    "SELECT env, tid, id, id, '[]', $1, 'envelope', NULL FROM rr",
    "INSERT INTO run_inputs (id, tenant_id, owner_run_id, root_run_id, sensitive_pointers, ciphertext, role, pointer) "
    "SELECT gen_random_uuid(), tid, id, id, '[]', $1, 'claim', '/x' FROM rr",
    "INSERT INTO run_requests (id, tenant_id, workflow_id, workflow_version_id, source, mode, idempotency_key, digest, "
    "digest_key_version, status, envelope_id, queued_at) SELECT id, tid, wid, vid, 'manual', 'live', id::text, $1, 1, "
    "'started', env, now() - interval '2 days' FROM rr",
    "INSERT INTO runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, kind, queued_at, started_at, "
    "ended_at) SELECT id, tid, wid, vid, 'live', 'succeeded', 'run', now() - interval '2 days', "
    "now() - interval '2 days', now() - interval '1 day' FROM rr",
    "CREATE TEMP TABLE sr AS SELECT gen_random_uuid() id, rr.id root, rr.vid, rr.wid, rr.tid FROM rr, "
    "generate_series(1, $2) k WHERE rr.n % $1 = 0",
    "INSERT INTO runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, kind, parent_run_id, queued_at, "
    "started_at, ended_at) SELECT id, tid, wid, vid, 'live', 'succeeded', 'subflow', root, now() - interval '2 days', "
    "now() - interval '2 days', now() - interval '1 day' FROM sr",
    "CREATE TEMP TABLE ar AS SELECT id, id root, tid FROM rr UNION ALL SELECT id, root, tid FROM sr",
    "INSERT INTO run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status) "
    "SELECT ar.tid, ar.id, gen_random_uuid(), '', 1, 'n', 'succeeded' FROM ar, generate_series(1, $1) k",
    "INSERT INTO step_outputs (id, tenant_id, owner_run_id, root_run_id, sensitive_pointers, ciphertext, kind) "
    "SELECT gen_random_uuid(), ar.tid, ar.id, ar.root, '[]', $2, 'output' FROM ar, generate_series(1, $1) k",
    "INSERT INTO claim_grants (claim_id, run_id, tenant_id, granted_by, root_run_id) "
    "SELECT o.id, sr.id, sr.tid, sr.root, sr.root FROM sr JOIN LATERAL (SELECT id FROM step_outputs "
    "WHERE owner_run_id = sr.root LIMIT 1) o ON true",
    "INSERT INTO run_secret_index (root_run_id, tenant_id, version, string_count, byte_count, ciphertext) "
    "SELECT id, tid, 1, 0, 0, $1 FROM rr",
    "INSERT INTO connections (id, tenant_id, type, name, config) "
    "SELECT gen_random_uuid(), t.id, 'http', 'c' || k, '{}' FROM t, generate_series(1, $1) k",
    "INSERT INTO data_keys (version, wrapped_key, kek_id, tenant_id) SELECT 1, $1, 'k', id FROM t",
    "INSERT INTO tenant_event_keys (tenant_id, version, public_key, private_sealed) SELECT id, 1, $1, $2 FROM t",
    "INSERT INTO tenant_event_counters (tenant_id) SELECT id FROM t",
    "INSERT INTO webhook_endpoints (id, tenant_id, name, auth_kind, bearer_digest, dedupe_key, created_by) "
    "SELECT gen_random_uuid(), tu.tid, 'e', 'bearer', $1, $1, tu.uid FROM tu",
    "CREATE TEMP TABLE te AS SELECT id eid, tenant_id tid FROM webhook_endpoints",
    "INSERT INTO trigger_bindings (id, tenant_id, endpoint_id, workflow_id, created_by) "
    "SELECT gen_random_uuid(), te.tid, te.eid, (SELECT wid FROM tw WHERE tw.tid = te.tid LIMIT 1), tu.uid "
    "FROM te JOIN tu ON tu.tid = te.tid",
    "INSERT INTO inbound_events (id, tenant_id, endpoint_id, key_version, sealed, size_bytes, status, ended_at) "
    "SELECT gen_random_uuid(), rr.tid, te.eid, 1, $1::bytea, octet_length($1::bytea), 'matched', "
    "now() - interval '1 day' FROM rr JOIN te ON te.tid = rr.tid",
    "INSERT INTO schedules (id, tenant_id, workflow_id, mode, created_by, every_s, offset_s, input) "
    "SELECT gen_random_uuid(), tw.tid, tw.wid, 'live', tu.uid, 3600, 0, $2 FROM tw JOIN tu ON tu.tid = tw.tid "
    "WHERE tw.n % $1 = 0",
    "INSERT INTO csv_mappings (workflow_id, tenant_id, mapping, saved_by, saved_against) "
    "SELECT DISTINCT ON (tw.tid) tw.wid, tw.tid, $1, tu.uid, tw.vid FROM tw JOIN tu ON tu.tid = tw.tid",
    "ANALYZE",
]


def _args(statement: str, tenants: int, roots: int) -> list[Any]:
    """Each seed statement's arguments, in the order its placeholders use them."""
    p = PROFILE
    table: dict[str, list[Any]] = {
        "INTO cel_profiles": [CEL], "INSERT INTO tenants": [tenants], "INSERT INTO users": [tenants * p["members"]],
        "INSERT INTO memberships": [p["members"]], "TABLE tu": [p["members"]],
        "INSERT INTO workflows": [p["workflows"]],
        "INSERT INTO workflow_versions": [p["versions"], CEL], "UPDATE workflows": [p["versions"]],
        "TABLE tw": [p["versions"]], "TABLE r ": [roots], "INSERT INTO run_inputs": [BLOB],
        "INSERT INTO run_requests": [DIGEST], "TABLE sr": [p["subrun_every"], p["subruns"]],
        "INSERT INTO run_steps": [p["steps_per_run"]], "INSERT INTO step_outputs": [p["outputs_per_run"], BLOB],
        "INSERT INTO run_secret_index": [BLOB], "INSERT INTO connections": [p["connections"]],
        "INSERT INTO data_keys": [BLOB], "INSERT INTO tenant_event_keys": [b"\x01" * 32, BLOB],
        "INSERT INTO webhook_endpoints": [BLOB], "INSERT INTO inbound_events": [BLOB],
        "INSERT INTO schedules": [max(1, p["workflows"] // p["schedules"]), BLOB], "INSERT INTO csv_mappings": [BLOB],
    }  # fmt: skip
    for key, args in table.items():
        if key in statement:
            return args
    return []


async def seed(url: str, roots: int) -> dict[str, int]:
    tenants = max(PROFILE["min_tenants"], roots // PROFILE["roots_per_tenant"])
    c = await asyncpg.connect(url)
    try:
        for statement in SEED:
            await c.execute(statement, *_args(statement, tenants, roots))
        counted = {}
        for table in ("tenants", "workflows", "workflow_versions", "runs", "run_steps", "run_inputs", "step_outputs",
                      "claim_grants", "run_requests", "inbound_events", "schedules", "connections"):  # fmt: skip
            counted[table] = int(await c.fetchval(f"SELECT count(*) FROM {table}"))  # noqa: S608
        return counted
    finally:
        await c.close()


class Load:
    """The normal load: one connection and one operation at a time per kind, each operation's time kept."""

    KINDS = ("read_runs", "read_tenant", "read_connections", "read_versions", "write_step", "write_run_end",
             "admit_request", "record_event")  # fmt: skip

    def __init__(self, url: str) -> None:
        self.url, self.stop = url, asyncio.Event()
        self.times: dict[str, list[tuple[float, float]]] = {k: [] for k in self.KINDS}
        self.errors: dict[str, dict[str, int]] = {k: {} for k in self.KINDS}
        self.pids: list[int] = []
        self.ids: dict[str, list[Any]] = {}

    async def prepare(self) -> None:
        c = await asyncpg.connect(self.url)
        try:
            for name, query in {
                "tenants": "SELECT id FROM tenants",
                "runs": "SELECT id FROM runs WHERE parent_run_id IS NULL LIMIT 2000",
                "workflows": "SELECT id FROM workflows LIMIT 2000",
                "versions": "SELECT id, workflow_id, tenant_id FROM workflow_versions WHERE number = 2 LIMIT 2000",
                "endpoints": "SELECT id, tenant_id FROM webhook_endpoints",
            }.items():  # fmt: skip
                self.ids[name] = list(await c.fetch(query))
        finally:
            await c.close()

    async def _op(self, c: asyncpg.Connection, kind: str) -> None:
        pick = random.choice  # noqa: S311  # synthetic load, no security meaning
        if kind == "read_runs":
            await c.fetch("SELECT id FROM runs WHERE tenant_id = $1 ORDER BY queued_at DESC LIMIT 50",
                          pick(self.ids["tenants"])["id"])  # fmt: skip
        elif kind == "read_tenant":
            await c.fetch("SELECT id, name, status FROM tenants WHERE id = $1", pick(self.ids["tenants"])["id"])
        elif kind == "read_connections":
            await c.fetch("SELECT id, name FROM connections WHERE tenant_id = $1", pick(self.ids["tenants"])["id"])
        elif kind == "read_versions":
            await c.fetch("SELECT id FROM workflow_versions WHERE workflow_id = $1", pick(self.ids["workflows"])["id"])
        elif kind == "write_step":
            run = pick(self.ids["runs"])["id"]
            await c.execute("INSERT INTO run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, "
                            "status) SELECT tenant_id, id, gen_random_uuid(), '', 1, 'n', 'succeeded' FROM runs "
                            "WHERE id = $1", run)  # fmt: skip
        elif kind == "write_run_end":
            await c.execute("UPDATE runs SET iterations = iterations + 1 WHERE id = $1", pick(self.ids["runs"])["id"])
        elif kind == "admit_request":  # its envelope and its request, in one transaction, as admission writes them
            v, request, envelope = pick(self.ids["versions"]), uuid.uuid4(), uuid.uuid4()
            async with c.transaction():
                await c.execute("INSERT INTO run_inputs (id, tenant_id, owner_run_id, root_run_id, sensitive_pointers, "
                                "ciphertext, role, pointer) VALUES ($1, $2, $3, $3, '[]', $4, 'envelope', NULL)",
                                envelope, v["tenant_id"], request, BLOB)  # fmt: skip
                await c.execute("INSERT INTO run_requests (id, tenant_id, workflow_id, workflow_version_id, source, "
                                "mode, idempotency_key, digest, digest_key_version, status, envelope_id) "
                                "VALUES ($1, $2, $3, $4, 'manual', 'live', $5, $6, 1, 'queued', $7)",
                                request, v["tenant_id"], v["workflow_id"], v["id"], uuid.uuid4().hex, DIGEST,
                                envelope)  # fmt: skip
        elif kind == "record_event":
            e = pick(self.ids["endpoints"])
            await c.execute(
                "INSERT INTO inbound_events (id, tenant_id, endpoint_id, key_version, sealed, size_bytes) "
                "VALUES ($1, $2, $3, 1, $4, $5)",
                uuid.uuid4(),
                e["tenant_id"],
                e["id"],
                BLOB,
                len(BLOB),
            )

    async def _loop(self, kind: str) -> None:
        c = await asyncpg.connect(self.url)
        self.pids.append(await c.fetchval("SELECT pg_backend_pid()"))
        try:
            while not self.stop.is_set():
                t0 = time.monotonic()
                try:
                    await self._op(c, kind)
                except asyncpg.PostgresError as e:  # counted by type, never by value; the loop carries on
                    self.errors[kind][type(e).__name__] = self.errors[kind].get(type(e).__name__, 0) + 1
                self.times[kind].append((t0, time.monotonic() - t0))
                await asyncio.sleep(PAUSE)
        finally:
            await c.close()


class Sampler:
    """The migrating backend's relation locks (granted) and statement, every SAMPLE seconds."""

    def __init__(self, url: str, skip: list[int]) -> None:
        self.url, self.skip, self.stop = url, skip, asyncio.Event()
        self.locks: dict[tuple[str, str], float] = {}  # (relation, mode): first seen, seconds from the upgrade's start
        self.names: dict[int, str] = {}  # every relation that existed before the upgrade: its oid, its name
        self.statements: list[tuple[float, str]] = []

    async def run(self, t0: float) -> None:
        c = await asyncpg.connect(self.url)
        me = await c.fetchval("SELECT pg_backend_pid()")
        self.names = {r["oid"]: r["relname"] for r in await c.fetch(
            "SELECT oid, relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p')"
        )}  # fmt: skip
        try:
            while not self.stop.is_set():
                found = await c.fetch("SELECT pid, left(query, 160) q FROM pg_stat_activity WHERE datname = "
                                      "current_database() AND pid <> $1 AND NOT (pid = ANY($2)) AND backend_type = "
                                      "'client backend' AND state <> 'idle'", me, self.skip)  # fmt: skip
                at = time.monotonic() - t0
                for row in found:
                    if not self.statements or self.statements[-1][1] != row["q"]:
                        self.statements.append((round(at, 2), row["q"]))
                    for lock in await c.fetch("SELECT relation::oid rel, mode FROM pg_locks WHERE pid = $1 "
                                              "AND locktype = 'relation' AND granted", row["pid"]):  # fmt: skip
                        name = self.names.get(lock["rel"])  # an index, or a relation the upgrade made: not reported
                        if name is not None:
                            self.locks.setdefault((name, lock["mode"]), round(at, 2))
                await asyncio.sleep(SAMPLE)
        finally:
            await c.close()


def _upgrade(url: str, marks: list[tuple[float, str]], t0: float) -> tuple[int, list[str]]:
    """`alembic upgrade head`, its "Running upgrade" lines stamped as they come; its exit and its last lines."""
    env = {**os.environ, "DEWPOINT_DATABASE_URL": url.replace("postgresql://", "postgresql+asyncpg://")}
    proc = subprocess.Popen([str(BACKEND / ".venv/bin/alembic"), "upgrade", "head"], cwd=BACKEND, env=env,  # noqa: S603
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # fmt: skip
    assert proc.stdout is not None
    tail: list[str] = []
    for line in proc.stdout:
        if "Running upgrade" in line:
            marks.append((round(time.monotonic() - t0, 2), line.split("Running upgrade", 1)[1].split(",")[0].strip()))
        elif line.strip():
            tail = [*tail, line.rstrip()][-30:]
    return proc.wait(), tail


# Lock modes that block a plain read (`ACCESS SHARE`), and those that block a write (`ROW EXCLUSIVE`)
BLOCK_READS = {"AccessExclusiveLock"}
BLOCK_WRITES = {"ShareLock", "ShareRowExclusiveLock", "ExclusiveLock", "AccessExclusiveLock"}


def _held(locks: dict[tuple[str, str], float], took: float) -> dict[str, dict[str, float]]:
    """Each existing table's reads and writes blocked from when the upgrade first took such a lock on it to its commit:
    how long a normal operation that arrived just then would wait."""
    held: dict[str, dict[str, float]] = {}
    for (rel, mode), at in locks.items():
        entry = held.setdefault(rel, {})
        for kind, modes in (("reads_blocked_s", BLOCK_READS), ("writes_blocked_s", BLOCK_WRITES)):
            if mode in modes:
                entry[kind] = max(entry.get(kind, 0.0), round(took - at, 2))
    return {rel: v for rel, v in sorted(held.items(), key=lambda x: -max(x[1].values(), default=0)) if v}


async def measure(url: str, *, loaded: bool) -> dict[str, Any]:
    load = Load(url)
    loops: list[asyncio.Task[None]] = []
    baseline: dict[str, float] = {}
    if loaded:
        await load.prepare()
        loops = [asyncio.create_task(load._loop(k)) for k in Load.KINDS]
        await asyncio.sleep(2)  # the load's baseline, before the upgrade
        baseline = {k: statistics.median(d for _, d in v) for k, v in load.times.items() if v}
    sampler = Sampler(url, load.pids)
    marks: list[tuple[float, str]] = []
    t0 = time.monotonic()
    sampling = asyncio.create_task(sampler.run(t0))
    code, tail = await asyncio.to_thread(_upgrade, url, marks, t0)
    took = time.monotonic() - t0
    if loaded:
        await asyncio.sleep(1)  # what the upgrade released
    load.stop.set()
    sampler.stop.set()
    await asyncio.gather(*loops, sampling)
    result: dict[str, Any] = {
        "upgrade_exit": code, "upgrade_s": round(took, 2), "migrations": marks,
        "held": _held(sampler.locks, took) if code == 0 else {},
        "locks": sorted([[rel, mode, at] for (rel, mode), at in sampler.locks.items()], key=lambda x: (x[2], x[0])),
        "statements": sampler.statements,
    }  # fmt: skip
    if code:
        result["upgrade_error"] = tail[-15:]
    if loaded:
        during = {k: [d for at, d in v if t0 - 1 <= at <= t0 + took] for k, v in load.times.items()}
        result["load"] = {k: {"ops": len(v), "baseline_ms": round(baseline.get(k, 0) * 1000, 2),
                              "max_wait_s": round(max(v, default=0), 3), "over_5s": sum(d > ACCEPT_S for d in v)}
                          for k, v in during.items()}  # fmt: skip
        result["errors"] = {k: v for k, v in load.errors.items() if v}
    return result


async def _copies(url: str, names: list[str]) -> None:
    """Copies of the seeded database, one per measured upgrade: each starts from the same data."""
    base, db = url.rsplit("/", 1)
    c = await asyncpg.connect(f"{base}/postgres")
    try:
        for name in names:
            await c.execute(f'CREATE DATABASE "{name}" TEMPLATE "{db}"')
    finally:
        await c.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("start", choices=["0034", "0042"])
    parser.add_argument("roots", type=int)
    parser.add_argument("--out")
    args = parser.parse_args()
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        url = pg.get_connection_url()
        env = {**os.environ, "DEWPOINT_DATABASE_URL": url.replace("postgresql://", "postgresql+asyncpg://")}
        subprocess.run([str(BACKEND / ".venv/bin/alembic"), "upgrade", args.start], cwd=BACKEND, env=env,  # noqa: S603
                       check=True, capture_output=True)  # fmt: skip
        t = time.monotonic()
        counts = asyncio.run(seed(url, args.roots))
        seeded_s = round(time.monotonic() - t, 1)
        asyncio.run(_copies(url, ["control", "loaded"]))
        base = url.rsplit("/", 1)[0]
        control = asyncio.run(measure(f"{base}/control", loaded=False))  # the upgrade alone: what it holds, how long
        loaded = asyncio.run(measure(f"{base}/loaded", loaded=True))  # the same under the normal load
    accepted = loaded["upgrade_exit"] == 0 and all(v["over_5s"] == 0 for v in loaded["load"].values())
    result = {"start": args.start, "roots": args.roots, "seeded": counts, "seed_s": seeded_s,
              "machine": {"platform": platform.platform(), "cpus": os.cpu_count(), "python": sys.version.split()[0]},
              "accepted": accepted, "control": control, "loaded": loaded}  # fmt: skip
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1, default=str))
    summary = {
        "start": args.start, "roots": args.roots, "seed_s": seeded_s, "accepted": accepted,
        "control": {"exit": control["upgrade_exit"], "upgrade_s": control["upgrade_s"],
                    "held": dict(list(control["held"].items())[:8])},
        "loaded": {"exit": loaded["upgrade_exit"], "upgrade_s": loaded["upgrade_s"], "errors": loaded["errors"],
                   "max_wait_s": max(v["max_wait_s"] for v in loaded["load"].values()),
                   "upgrade_error": [line for line in loaded.get("upgrade_error", []) if "Error" in line][-2:]},
    }  # fmt: skip
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
