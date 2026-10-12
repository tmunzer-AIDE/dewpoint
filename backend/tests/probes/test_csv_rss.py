# SPDX-License-Identifier: Apache-2.0
"""A CSV's work as one API process sees it (the owner's rulings 2 and 6 on 2b-4b's M3 checkpoint): `JOBS` worst-case
uploads at once, then `JOBS` worst-case starts of them at once (`csv_memory.py`'s `short` shape: 5 MiB, 200
two-character cells a row, every column declared), each through its transaction's commit, through the API app in this
process. Per phase: the process's resident memory (`ps`, every 50 ms: Python's own allocations, the allocator's overhead
and what it keeps), before, at its peak and after, and on macOS its physical footprint too (its compressed pages
counted, which a machine short of memory leaves out of the resident set); the event loop's longest wait for a turn; and
the latency of a cheap request (`/health/ready`, a database round trip) asked every 100 ms meanwhile.
`DEWPOINT_PROBE_INLINE=1` runs the CPU steps on the loop, as before the ruling, for comparison.

A probe, run by hand on a quiet machine, never in CI: about a minute. Each mode and job count in its own process, so
one run's memory isn't another's. From `backend/`:

    DEWPOINT_PROBE=1 [DEWPOINT_PROBE_JOBS=2] [DEWPOINT_PROBE_INLINE=1] [DEWPOINT_PROBE_OUT=FILE] \\
        .venv/bin/pytest -p no:cacheprovider -n 0 -s tests/probes/test_csv_rss.py

Numbers depend on the machine and its allocator (this one's, not a Linux container's glibc): record them with it."""

import asyncio
import ctypes
import gc
import json
import os
import platform
import resource
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from dewpoint.engine.graph.csv import MAX_BYTES, MAX_ROWS
from tests.apps.api.test_csv_uploads_api import CSV_TYPE, uploads_url
from tests.apps.api.test_run_requests_api import as_role, runs_url
from tests.apps.test_admission import KEYS, SCHEMA, TOKEN, current, published
from tests.probes.csv_memory import shapes

pytestmark = [
    pytest.mark.skipif(not os.environ.get("DEWPOINT_PROBE"), reason="a probe, run by hand (DEWPOINT_PROBE)"),
    pytest.mark.usefixtures("development_deployment"),
]
JOBS = int(os.environ.get("DEWPOINT_PROBE_JOBS", "2"))
INLINE = bool(os.environ.get("DEWPOINT_PROBE_INLINE"))
ROWS = int(os.environ.get("DEWPOINT_PROBE_ROWS", str(MAX_ROWS)))  # fewer for a quick check of the probe itself
SHAPE = "short"
MIB = 1024 * 1024


def _rss() -> int:
    """This process's resident set, in bytes."""
    found = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True, check=True)
    return int(found.stdout.strip()) * 1024


_LIBSYSTEM = ctypes.CDLL("/usr/lib/libSystem.B.dylib") if sys.platform == "darwin" else None
_V4, _FOOTPRINT, _LIFETIME_MAX = 4, 2 + 7, 2 + 28  # rusage_info_v4: its 16-byte uuid, then 64-bit fields


def _footprint() -> tuple[int, int]:
    """macOS: this process's physical footprint and its lifetime peak, in bytes (0, 0 elsewhere)."""
    if _LIBSYSTEM is None:
        return 0, 0
    info = (ctypes.c_uint64 * 64)()
    if _LIBSYSTEM.proc_pid_rusage(os.getpid(), _V4, ctypes.byref(info)) != 0:
        return 0, 0
    return int(info[_FOOTPRINT]), int(info[_LIFETIME_MAX])


class Sampled:
    """The resident set's and the footprint's largest samples while watched, every 50 ms from a thread of its own."""

    def __init__(self) -> None:
        self.most = self.footprint = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.is_set():
            self.most = max(self.most, _rss())
            self.footprint = max(self.footprint, _footprint()[0])
            self._stop.wait(0.05)

    def __enter__(self) -> "Sampled":
        self._thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        self._thread.join()
        self.most = max(self.most, _rss())
        self.footprint = max(self.footprint, _footprint()[0])


def _pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))] if ordered else 0.0


async def _phase(client: Any, jobs: list[Any]) -> tuple[list[Any], dict[str, Any]]:
    gc.collect()
    before, (footprint, _) = _rss(), _footprint()
    stop = asyncio.Event()
    stalls: list[float] = []
    asked: list[float] = []

    async def ticking() -> None:
        while not stop.is_set():
            begun = time.perf_counter()
            await asyncio.sleep(0.005)
            stalls.append(time.perf_counter() - begun - 0.005)

    async def asking() -> None:
        while not stop.is_set():
            begun = time.perf_counter()
            assert (await client.get("/health/ready")).status_code == 200
            asked.append(time.perf_counter() - begun)
            await asyncio.sleep(0.1)

    with Sampled() as sampled:
        watchers = [asyncio.create_task(ticking()), asyncio.create_task(asking())]
        begun = time.perf_counter()
        answers = await asyncio.gather(*jobs)
        took = time.perf_counter() - begun
        stop.set()
        await asyncio.gather(*watchers)
    gc.collect()
    after, (footprint_after, _) = _rss(), _footprint()
    ms = [s * 1000 for s in stalls]
    ready = [a * 1000 for a in asked]
    return answers, {
        "took_s": round(took, 1), "rss_before_mib": round(before / MIB, 1),
        "rss_peak_mib": round(sampled.most / MIB, 1),
        "rss_peak_over_before_mib": round((sampled.most - before) / MIB, 1), "rss_after_mib": round(after / MIB, 1),
        "footprint_before_mib": round(footprint / MIB, 1), "footprint_peak_mib": round(sampled.footprint / MIB, 1),
        "footprint_after_mib": round(footprint_after / MIB, 1),
        "loop_wait_max_ms": round(max(ms), 1) if ms else None, "loop_wait_p99_ms": round(_pct(ms, 0.99), 1),
        "ready_asked": len(ready), "ready_p50_ms": round(_pct(ready, 0.5), 1),
        "ready_p95_ms": round(_pct(ready, 0.95), 1), "ready_max_ms": round(max(ready), 1) if ready else None,
    }  # fmt: skip


async def test_concurrent_worst_case_csv_uploads_then_starts_in_one_process(
    app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:  # fmt: skip
    if INLINE:

        async def inline(step: Any, /, *args: Any, **kwargs: Any) -> Any:
            return step(*args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", inline)
    app.state.keys = KEYS
    data, columns = shapes(ROWS)[SHAPE]
    csv = {"columns": columns, "max_rows": MAX_ROWS, "max_bytes": MAX_BYTES}
    graph = {"graph_format": 1, "nodes": [{"id": "6f0c3c55-4a8e-4c43-9a1a-6a2b1f7f0c01", "key": "a",
             "type": "testkit.echo@1", "config": {"value": 1}}], "edges": [],
             "settings": {"input_schema": SCHEMA, "csv": csv}}  # fmt: skip
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph)
    await current(dispatch_sessionmaker)
    client = await as_role(app, owner_sessionmaker, api_settings, ctx)
    assert (await client.get("/health/ready")).status_code == 200  # the app warmed: its modules, its pools
    gc.collect()
    idle, (footprint_idle, _) = _rss(), _footprint()

    uploads = [client.post(uploads_url(ctx, wf), content=data, headers=CSV_TYPE) for _ in range(JOBS)]
    answers, uploaded = await _phase(client, uploads)
    assert [a.status_code for a in answers] == [201] * JOBS, answers[0].text
    ids = [a.json()["upload_id"] for a in answers]
    mapping = {c["name"]: c["header"] for c in columns}
    body = {"input": {"token": TOKEN, "site": "a"}, "mode": "live"}
    starts = [
        client.post(
            runs_url(ctx, wf),
            json=body | {"csv": {"upload_id": i, "mapping": mapping, "skip_invalid": True}},
            headers={"Idempotency-Key": f"rss-{n}"},
        )  # fmt: skip
        for n, i in enumerate(ids)
    ]
    answers, started = await _phase(client, starts)
    assert [a.status_code for a in answers] == [202] * JOBS, answers[0].text
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = {
        "python": sys.version.split()[0], "machine": platform.machine(), "system": platform.system(),
        "mode": "inline" if INLINE else "thread", "jobs": JOBS, "shape": SHAPE, "bytes": len(data),
        "rows": data.count(b"\n") - 1, "rss_idle_mib": round(idle / MIB, 1),
        "footprint_idle_mib": round(footprint_idle / MIB, 1),
        "footprint_lifetime_max_mib": round(_footprint()[1] / MIB, 1),
        "ru_maxrss_mib": round(peak / (MIB if sys.platform == "darwin" else 1024), 1),
        "uploads": uploaded, "starts": started,
    }  # fmt: skip
    print(json.dumps(result))
    out = os.environ.get("DEWPOINT_PROBE_OUT")
    if out:
        Path(out).write_text(json.dumps(result, indent=1))  # noqa: ASYNC240  # once, at the end
