# SPDX-License-Identifier: Apache-2.0
"""A CSV's work in the API's own Linux container (the owner's ruling 4 on 2b-4b's M3 checkpoint 2: the production
sizing needs a Linux process, not a macOS footprint). The app image (deploy/docker/app.Dockerfile, its pinned bases)
runs the API as Compose would, under a memory limit, beside a `postgres:16-alpine` container migrated and seeded as
Compose's migrate step does; then, from the host, `JOBS` worst-case uploads at once and `JOBS` worst-case starts of
them at once (`csv_memory.py`'s `short` shape), each through its commit. Sampled every 250 ms: the API process's
resident set (`/proc/1/status` VmRSS, VmHWM its peak) and its container's memory (`memory.current`, `memory.peak`:
the cgroup's, the page cache with it); and a cheap request's latency (`/health/ready`, a database round trip) every
100 ms meanwhile. Whether the container was killed for its memory is read back.

A probe, run by hand on a quiet machine, never in CI: a few minutes, and Docker. Every credential is random and
throwaway, never printed; every container and the network are removed at the end. From `backend/`:

    PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.csv_container --image IMAGE [--memory 1g] [--jobs 2] \\
        [--rounds 1] [--malloc-arena-max N] [--out FILE]

IMAGE is the app image built from this tree: `docker build -f deploy/docker/app.Dockerfile -t IMAGE .` at the
repository's root. Numbers depend on the machine (its Docker VM's CPUs, kernel and architecture): record them."""

import argparse
import asyncio
import base64
import json
import os
import platform
import secrets
import subprocess
import threading
import time
import uuid
from typing import Any

import httpx

from dewpoint.core.auth.sessions import SESSION_COOKIE
from dewpoint.engine.graph.csv import MAX_BYTES, MAX_ROWS
from tests.probes.csv_memory import shapes

PG_IMAGE = "postgres:16-alpine"  # Compose's pin
PORT = 18_000  # the API on the host's loopback only
ORIGIN = "http://localhost:8080"
SHAPE = "short"
MIB = 1024 * 1024
ROLES = ("API", "ADMIN", "AUDITOR", "WORKER", "DISPATCH", "INGRESS", "RETENTION")
INITDB = os.path.join(os.path.dirname(__file__), "..", "..", "..", "deploy", "compose", "initdb")

SEED = r"""
import asyncio, json, sys, uuid
from dewpoint.apps import workflow_ops
from dewpoint.core.auth.sessions import create_session
from dewpoint.core.auth.users import create_user
from dewpoint.core.config import get_settings
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import make_engine, make_sessionmaker, tenant_scope
from dewpoint.core.http import TenantContext
from dewpoint.core.tenancy.service import create_tenant
from dewpoint.core.workflows import service as workflows
from sqlalchemy import text

COLUMNS = int(sys.argv[1])
GRAPH = {"graph_format": 1, "nodes": [{"id": "5f0c6e2a-2b2b-4e2b-9c2b-2b2b2b2b2b2c", "key": "t",
         "type": "flow.transform@1", "config": {"fields": {"n": {"$value": {"kind": "cel", "expr": "1"}}}},
         "options": {"on_error": "fail"}}], "edges": [],
         "settings": {"input_schema": {"type": "object", "properties": {}},
                      "csv": {"columns": [{"header": f"c{i}", "name": f"c{i}", "type": "string"}
                                          for i in range(COLUMNS)]}}}


async def seed():
    settings = get_settings()
    engine = make_engine(settings.database_url)
    sm = make_sessionmaker(engine)
    async with sm() as s, s.begin():
        user = await create_user(s, email=f"probe-{uuid.uuid4().hex[:8]}@example.com",
                                 password="violet-otter-canyon-" + uuid.uuid4().hex)
        tenant = await create_tenant(s, Keyring(KekSet.from_settings(settings)), name="CSV probe",
                                     slug=f"csv-{uuid.uuid4().hex[:8]}", owner_id=user.id)
        session, token = await create_session(s, user_id=user.id, state="active", methods=["password", "totp"],
                                              settings=settings, ip=None, user_agent=None)
    ctx = TenantContext(tenant_id=tenant.id, user=user, role="owner", session=None)
    async with sm() as s, s.begin():
        await tenant_scope(s, tenant.id)
        wf = await workflows.create_workflow(s, ctx, name="CSV probe", draft=GRAPH)
    async with sm() as s, s.begin():
        await tenant_scope(s, tenant.id)
        found = await workflows.get_workflow(s, tenant.id, wf.id, for_update=True)
        published = await workflow_ops.publish(s, ctx, found, expected_revision=found.draft_revision,
                                               settings=settings)
        assert published.version is not None, published.errors
    await engine.dispose()
    print(json.dumps({"tenant": str(tenant.id), "workflow": str(wf.id), "token": token,
                      "csrf": session.csrf_token}))


asyncio.run(seed())
"""


def _docker(*args: str, stdin: str | None = None, check: bool = True) -> str:
    done = subprocess.run(["docker", *args], input=stdin, capture_output=True, text=True, check=False)
    if check and done.returncode != 0:
        raise RuntimeError(f"docker {args[0]} failed: {done.stderr.strip()[-400:]}")
    return done.stdout


class Stack:
    """The network, Postgres and the API's container, named for this run, removed at the end."""

    def __init__(self, image: str, memory: str, arenas: int | None = None) -> None:
        self.image, self.memory, self.arenas, self.mark = image, memory, arenas, uuid.uuid4().hex[:8]
        self.net, self.pg, self.api = f"csvprobe-{self.mark}", f"csvprobe-pg-{self.mark}", f"csvprobe-api-{self.mark}"
        self.passwords = {role: secrets.token_urlsafe(18) for role in ("OWNER", *ROLES)}
        self.kek = base64.b64encode(os.urandom(32)).decode()

    def url(self, login: str, role: str) -> str:
        return f"postgresql+asyncpg://{login}:{self.passwords[role]}@{self.pg}/dewpoint"

    def app_env(self, url: str) -> list[str]:
        values = {"DEWPOINT_KEK_B64": self.kek, "DEWPOINT_KEK_ID": "probe-1", "DEWPOINT_PUBLIC_ORIGIN": ORIGIN,
                  "DEWPOINT_RP_ID": "localhost", "DEWPOINT_TEMPORAL_NAMESPACE": "default",
                  "DEWPOINT_ENVIRONMENT": "development", "DEWPOINT_DATABASE_URL": url}  # fmt: skip
        return [arg for k, v in values.items() for arg in ("-e", f"{k}={v}")]

    def up(self) -> dict[str, str]:
        _docker("network", "create", self.net)
        pg_env = {"POSTGRES_DB": "dewpoint", "POSTGRES_USER": "dewpoint_owner",
                  "POSTGRES_PASSWORD": self.passwords["OWNER"],
                  **{f"DEWPOINT_{role}_DB_PASSWORD": self.passwords[role] for role in ROLES}}  # fmt: skip
        _docker("run", "-d", "--name", self.pg, "--network", self.net,
                *[arg for k, v in pg_env.items() for arg in ("-e", f"{k}={v}")],
                "-v", f"{os.path.abspath(INITDB)}:/docker-entrypoint-initdb.d:ro", PG_IMAGE)  # fmt: skip
        for _ in range(120):
            ready = _docker("exec", self.pg, "pg_isready", "-U", "dewpoint_owner", "-d", "dewpoint", check=False)
            if "accepting connections" in ready:
                break
            time.sleep(1)
        time.sleep(2)  # the init scripts' restart
        owner = self.url("dewpoint_owner", "OWNER")
        admin = self.url("dewpoint_admin_login", "ADMIN")
        _docker("run", "--rm", "--network", self.net, *self.app_env(owner), self.image, "sh", "-c",
                "set -e; alembic upgrade head; dewpoint platform init-environment; "
                f"DEWPOINT_DATABASE_URL={admin} dewpoint plugins sync")  # fmt: skip
        seeded = _docker("run", "--rm", "-i", "--network", self.net, *self.app_env(owner), self.image,
                         "python", "-", "200", stdin=SEED)  # fmt: skip
        self.build()
        _docker("run", "-d", "--name", self.api, "--network", self.net, "--memory", self.memory,
                "--memory-swap", self.memory, "-p", f"127.0.0.1:{PORT}:8000",
                *(("-e", f"MALLOC_ARENA_MAX={self.arenas}") if self.arenas else ()),
                *self.app_env(self.url("dewpoint_api_login", "API")), self.image)  # fmt: skip
        found: dict[str, str] = json.loads(seeded.strip().splitlines()[-1])
        return found

    def build(self) -> None:
        """The current build, as the dispatcher records it: admission needs one seen in the last two minutes."""
        from dewpoint.engine import ENGINE_ABI

        _docker("exec", self.pg, "psql", "-U", "dewpoint_owner", "-d", "dewpoint", "-qc",
                "insert into current_build (id, build_id, engine_abi, observed_at) values (1, 'csv-probe', "
                f"{ENGINE_ABI}, now()) on conflict (id) do update set observed_at = now()")  # fmt: skip

    def sample(self) -> dict[str, int]:
        out = _docker("exec", self.api, "sh", "-c", "grep -E '^Vm(RSS|HWM):' /proc/1/status; "
                      "cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak", check=False)  # fmt: skip
        lines = out.split()
        try:
            rss = int(lines[lines.index("VmRSS:") + 1]) * 1024
            hwm = int(lines[lines.index("VmHWM:") + 1]) * 1024
            current, peak = int(lines[-2]), int(lines[-1])
        except (ValueError, IndexError):
            return {}
        return {"rss": rss, "hwm": hwm, "cgroup": current, "cgroup_peak": peak}

    def killed(self) -> dict[str, Any]:
        state = json.loads(_docker("inspect", self.api, "--format", "{{json .State}}", check=False) or "{}")
        return {"oom_killed": state.get("OOMKilled"), "running": state.get("Running"), "exit": state.get("ExitCode")}

    def down(self) -> None:
        for name in (self.api, self.pg):
            _docker("rm", "-f", "-v", name, check=False)
        _docker("network", "rm", self.net, check=False)


class Sampled:
    def __init__(self, stack: Stack) -> None:
        self.stack, self.most, self._stop = stack, dict[str, int](), threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            for k, v in self.stack.sample().items():
                self.most[k] = max(self.most.get(k, 0), v)
            self._stop.wait(0.25)

    def __enter__(self) -> "Sampled":
        self._thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        self._thread.join()


def _pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))] if ordered else 0.0


def _mib(sample: dict[str, int]) -> dict[str, float]:
    return {k: round(v / MIB, 1) for k, v in sample.items()}


async def _phase(stack: Stack, client: httpx.AsyncClient, jobs: list[Any]) -> tuple[list[Any], dict[str, Any]]:
    before = stack.sample()
    stop, asked = asyncio.Event(), list[float]()

    async def asking() -> None:
        while not stop.is_set():
            begun = time.perf_counter()
            assert (await client.get("/health/ready")).status_code == 200
            asked.append((time.perf_counter() - begun) * 1000)
            await asyncio.sleep(0.1)

    with Sampled(stack) as sampled:
        watcher = asyncio.create_task(asking())
        begun = time.perf_counter()
        answers = await asyncio.gather(*jobs)
        took = time.perf_counter() - begun
        stop.set()
        await watcher
    return answers, {
        "took_s": round(took, 1), "before_mib": _mib(before), "most_mib": _mib(sampled.most),
        "after_mib": _mib(stack.sample()), "ready_asked": len(asked), "ready_p50_ms": round(_pct(asked, 0.5), 1),
        "ready_p95_ms": round(_pct(asked, 0.95), 1), "ready_max_ms": round(max(asked), 1) if asked else None,
    }  # fmt: skip


async def drive(stack: Stack, seeded: dict[str, str], jobs: int, rounds: int) -> dict[str, Any]:
    data, columns = shapes(MAX_ROWS)[SHAPE]
    headers = {"X-Dewpoint-Client": "web", "X-CSRF-Token": seeded["csrf"], "Origin": ORIGIN,
               "Cookie": f"{SESSION_COOKIE}={seeded['token']}"}  # fmt: skip
    base = f"/api/v1/t/{seeded['tenant']}/workflows/{seeded['workflow']}"
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORT}", headers=headers, timeout=300) as client:
        for _ in range(120):
            try:
                if (await client.get("/health/ready")).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            await asyncio.sleep(1)
        idle = stack.sample()
        measured = []
        for r in range(rounds):  # the same work again: whether what the allocator keeps grows with it
            uploads = [client.post(f"{base}/csv-uploads", content=data, headers={"Content-Type": "text/csv"})
                       for _ in range(jobs)]  # fmt: skip
            answers, uploaded = await _phase(stack, client, uploads)
            assert [a.status_code for a in answers] == [201] * jobs, answers[0].text[:300]
            mapping = {c["name"]: c["header"] for c in columns}
            stack.build()  # seen within the admission's two minutes
            starts = [
                client.post(f"{base}/runs", headers={"Idempotency-Key": f"probe-{r}-{n}"},
                            json={"input": {}, "mode": "live",
                                  "csv": {"upload_id": a.json()["upload_id"], "mapping": mapping,
                                          "skip_invalid": True}})
                for n, a in enumerate(answers)
            ]  # fmt: skip
            answers, started = await _phase(stack, client, starts)
            assert [a.status_code for a in answers] == [202] * jobs, answers[0].text[:300]
            measured.append({"uploads": uploaded, "starts": started})
    return {"idle_mib": _mib(idle), "rounds": measured}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--memory", default="1g")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--malloc-arena-max", type=int, help="glibc's arenas at most, in the API's container")
    parser.add_argument("--out")
    args = parser.parse_args()
    stack = Stack(args.image, args.memory, args.malloc_arena_max)
    result: dict[str, Any] = {}
    try:
        seeded = stack.up()
        measured = asyncio.run(drive(stack, seeded, args.jobs, args.rounds))
        result = {"image": args.image, "memory_limit": args.memory, "jobs": args.jobs, "shape": SHAPE,
                  "malloc_arena_max": args.malloc_arena_max,
                  "bytes_cap": MAX_BYTES, "host": platform.machine(),
                  "docker": _docker("version", "--format", "{{.Server.Os}}/{{.Server.Arch}}").strip(),
                  **measured}  # fmt: skip
    finally:
        result["container"] = stack.killed()  # killed for its memory, or not, before it's removed
        stack.down()
    text = json.dumps(result, indent=1)
    print(text)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
