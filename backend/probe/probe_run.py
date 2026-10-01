"""Throwaway (2b-1b go/no-go, spec 2b §5.3): runs a scenario on Temporal against the prototype (time-skipping server,
or the CLI dev server with DEV=1) and reports, for every execution a run led to (its continues and its children):
- every continued-run input: its encoded bytes (the payload as Temporal holds it) and its parts, decrypted;
- peak open iteration scopes (the prototype's probe), against OPEN_SCOPES_CAP + D;
- continues, history events and bytes;
- restore equivalence: each snapshot's scheduler, restored, encodes again identically (and rebuilds its queues);
- replay: every history replays through the Replayer;
- completion within a fixed timeout (no progress = a failure).
Run from the proto's backend/:  PYTHONPATH=. uv run python ../../exp/probe_run.py <scenario> [...]"""

import asyncio
import contextlib
import json
import os
import pathlib
import sys
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer

from dewpoint.engine.runtime import probe
from dewpoint.engine.runtime.program import compile_program
from dewpoint.engine.runtime.scheduler import OPEN_SCOPES_CAP, Scheduler
from dewpoint.engine.runtime.size import SNAPSHOT_BYTES
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.apps.worker.harness import MemoryStore, start, workers
from tests.engine.replay.record import executions
from tests.support.graphs import G, cel, ref
from tests.support.keys import FIXTURE_CONVERTER, opened

TIMEOUT_S = int(os.environ.get("PROBE_TIMEOUT", "900"))
OUT = pathlib.Path(__file__).with_name("results.jsonl")
LOOP = "flow.loop@1"


def size(v: Any) -> int:
    return len(json.dumps(v, separators=(",", ":"), default=str))


# --- workloads: every graph goes through MemoryStore.add, which validates it as publishing does ----------------------


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": outputs}
    return g


def loop(g: G, key: str, items: Any, conc: int = 10, collect: Any = None) -> None:
    g.node(key, LOOP, {"items": items, "concurrency": conc, "collect": collect if collect is not None else ref("item")})


def wide_nested(width: int, outer: int = 10, inner: int = 10, g: G | None = None, p: str = "") -> G:
    """Nested outer x inner (up to 100 open inner iterations), the inner body `width` parallel steps and a join."""
    g = g or graph(n=ref(f"steps.{p}o.output.count"))
    loop(g, f"{p}o", list(range(outer)))
    loop(g, f"{p}i", list(range(inner)))
    g.edge(f"{p}o", f"{p}i", "body")
    g.node(f"{p}j", "flow.transform@1", {"fields": {"v": ref("item")}})
    for n in range(width):
        g.node(f"{p}x{n}", "testkit.echo@1", {"value": ref("item")}).edge(f"{p}i", f"{p}x{n}", "body")
        g.edge(f"{p}x{n}", f"{p}j")
    return g


def wide_flat(width: int, items: int = 100) -> G:
    g = graph(n=ref("steps.o.output.count"))
    loop(g, "o", list(range(items)))
    g.node("j", "flow.transform@1", {"fields": {"v": ref("item")}})
    for n in range(width):
        g.node(f"x{n}", "testkit.echo@1", {"value": ref("item")}).edge("o", f"x{n}", "body").edge(f"x{n}", "j")
    return g


def nested3(a: int, b: int, c: int, g: G | None = None, p: str = "") -> G:
    g = g or graph(n=ref(f"steps.{p}a.output.count"))
    loop(g, f"{p}a", list(range(a)))
    loop(g, f"{p}b", list(range(b)))
    loop(g, f"{p}c", list(range(c)))
    g.node(f"{p}x", "testkit.echo@1", {"value": ref("item")})
    g.edge(f"{p}a", f"{p}b", "body").edge(f"{p}b", f"{p}c", "body").edge(f"{p}c", f"{p}x", "body")
    return g


def siblings(k: int, n: int, inner: int, g: G | None = None, p: str = "") -> G:
    g = g or graph(n=ref(f"steps.{p}s0.output.count"))
    for j in range(k):
        loop(g, f"{p}s{j}", list(range(n)))
        loop(g, f"{p}i{j}", list(range(inner)))
        g.node(f"{p}x{j}", "testkit.echo@1", {"value": ref("item")})
        g.edge(f"{p}s{j}", f"{p}i{j}", "body").edge(f"{p}i{j}", f"{p}x{j}", "body")
    return g


def combined_struct() -> G:
    """Every structural limit at once, within the graph's 500 nodes: a wide nested body, a 3-deep nest, sibling loops
    and sleeping timers, all in parallel from the root."""
    g = graph(w=ref("steps.wo.output.count"), n=ref("steps.na.output.count"))
    wide_nested(300, g=g, p="w")
    nested3(20, 10, 10, g=g, p="n")
    siblings(5, 20, 10, g=g, p="s")
    for k in range(20):
        g.node(f"d{k}", "flow.delay@1", {"duration_s": 5})
    return g


SCENARIOS: dict[str, Callable[[], G]] = {
    "wide_nested_480": lambda: wide_nested(480),
    "wide_flat_496": lambda: wide_flat(496),
    "nested3_100x10x10": lambda: nested3(100, 10, 10),
    "siblings_20x20x10": lambda: siblings(20, 20, 10),
    "combined_struct": combined_struct,
}


# --- measurement ----------------------------------------------------------------------------------------------------


def parts(inp: dict[str, Any]) -> dict[str, int]:
    snap = inp.get("snapshot") or {}
    s = snap.get("scheduler") or {}
    scopes, loops = s.get("scopes", []), s.get("loops", [])
    return {
        "input_json": size(inp),
        "snapshot": size(snap),
        "trigger": size(inp.get("trigger")),
        "outer": size(inp.get("outer")),
        "batch_items": size(inp.get("items")),
        "scopes": size(scopes),
        "scope_codes": sum(len(sc[2]) + len(sc[3]) for sc in scopes),
        "scope_results": sum(size(sc[4]) for sc in scopes),
        "scope_items": sum(size(sc[5]) for sc in scopes),
        "loops": size(loops),
        "loop_items": sum(size(lp[1]) for lp in loops),
        "loop_collected": sum(size(lp[9]) for lp in loops),
        "loop_failures": sum(size(lp[10]) for lp in loops),
        "handed": size(s.get("handed")),
        "budget": size(s.get("budget")),
        "timers": size(snap.get("timers")),
        "variables": size(snap.get("variables")),
        "secrets": size(snap.get("secrets")),
        "n_scopes": len(scopes),
        "n_open": sum(1 for sc in scopes if sc[0] and not sc[8]),
    }


async def measure(histories: list[WorkflowHistory], store: MemoryStore) -> dict[str, Any]:
    continues, restored = [], 0
    events = history_bytes = 0
    programs: dict[str, Any] = {}
    for h in histories:
        events += len(h.events)
        history_bytes += sum(e.ByteSize() for e in h.events)
        for e in h.events:
            if e.event_type != EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW:
                continue
            payloads = e.workflow_execution_continued_as_new_event_attributes.input.payloads
            [payload] = payloads
            inp = await opened(payload)
            vid = inp["version_id"]
            if vid not in programs:
                v = store.versions[vid]
                programs[vid] = compile_program(
                    v.graph, v.manifests, v.expressions, v.cel_profile, v.subflow_version_ids, v.failure_handler_version_id
                )
            snap = inp["snapshot"]["scheduler"]
            sched = Scheduler.from_json(programs[vid], snap)
            again = json.loads(json.dumps(sched.to_json()))
            assert again == snap, f"{h.workflow_id}: a snapshot doesn't restore identically"
            restored += 1
            live = getattr(sched, "live", 0)
            relief = sched._relief() if hasattr(sched, "_relief") else 0
            pending = sum(len(lp.items_pending) for lp in sched.loops.values()) if hasattr(sched, "_relief") else 0
            inline_lists = sum(1 for lp in sched.loops.values() if isinstance(lp.items, list))
            continues.append({"encoded": payload.ByteSize(), "batch": "outer" in inp, "live": live, "relief": relief,
                              "pending_item_segments": pending, "inline_item_lists": inline_lists, **parts(inp)})
    return {"continues": continues, "restored": restored, "events": events, "history_bytes": history_bytes}


async def replay(histories: list[WorkflowHistory]) -> int:
    async def each() -> AsyncIterator[WorkflowHistory]:
        for h in histories:
            yield h

    replayer = Replayer(workflows=[RunGraph, LoopBatch], data_converter=FIXTURE_CONVERTER)
    results = await replayer.replay_workflows(each(), raise_on_replay_failure=True)
    return len(histories)


@contextlib.asynccontextmanager
async def versioned(client: Any, store: MemoryStore, build_id: str) -> AsyncIterator[None]:
    """Build `build_id`'s workers, made current: the same build again after a restart, so pinned runs find it."""
    from dewpoint.apps.worker.activities import cel_activity
    from dewpoint.apps.worker.deployment import set_current
    from dewpoint.apps.worker.main import engine_worker
    from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
    from dewpoint.engine.runtime.activities import cel_queue
    from temporalio.worker import Worker
    from tests.apps.worker.harness import in_process
    from tests.apps.worker.test_main import settings
    from tests.support.plugins.testkit import TESTKIT

    import functools

    from dewpoint.apps.worker import main as worker_main
    from timing_runner import TimingRunner

    extra: dict[str, Any] = {"workflow_runner": TimingRunner()}  # each activation's CPU and wall time
    slots = os.environ.get("WFT_SLOTS")  # the engine worker's workflow-task slots (the SDK's default when unset)
    if slots:
        extra["max_concurrent_workflow_tasks"] = int(slots)
    worker_main.Worker = functools.partial(Worker, **extra)  # type: ignore[misc]
    evaluator = Worker(client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process)])
    async with evaluator, engine_worker(client, store, [TESTKIT], settings(), build=build_id, identity=build_id):
        await set_current(client, build_id)
        yield


def serve(client: Any, store: MemoryStore, build_id: str = "probe-build") -> Any:
    """The engine's workers: on the dev server, a versioned build made current (the workflows are Pinned, as the
    repository's dev-server tests serve them); on the time-skipping server, which has no Worker Deployments, plain."""
    if os.environ.get("DEV") == "1":
        return versioned(client, store, build_id)
    return workers(client, store)


async def environment() -> WorkflowEnvironment:
    address = os.environ.get("TEMPORAL_ADDRESS")  # an external dev server (the Linux probe's container)
    if address:
        from temporalio.client import Client

        return WorkflowEnvironment.from_client(await Client.connect(address, data_converter=FIXTURE_CONVERTER))
    if os.environ.get("DEV") == "1":
        return await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER)
    return await WorkflowEnvironment.start_time_skipping(data_converter=FIXTURE_CONVERTER)


async def run(name: str) -> dict[str, Any]:
    g = SCENARIOS[name]()
    store = MemoryStore()
    probe.PEAKS.clear()
    t0 = time.monotonic()
    status, error = "timeout", None
    async with await environment() as env:
        async with serve(env.client, store):
            handle = await start(env.client, store, g, {}, checkpoint_events=300, drain_events=600)
            print("    run", handle.id, flush=True)
            try:
                result = await asyncio.wait_for(handle.result(), TIMEOUT_S)
                status, error = result.status, result.error
            except TimeoutError:
                pass
            elapsed = time.monotonic() - t0
            histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
    m = await measure(histories, store)
    replayed = await replay(histories)
    ids = {h.workflow_id for h in histories}
    peaks = [probe.PEAKS.get(i, {}) for i in ids]
    c = m["continues"]
    worst = {k: max((x[k] for x in c), default=0) for k in (c[0] if c else {}) if k != "batch"}
    out = {
        "scenario": name,
        "server": "dev" if os.environ.get("DEV") == "1" else "time-skipping",
        "nodes": len(g.nodes),
        "status": status,
        "error": error,
        "elapsed_s": round(elapsed, 1),
        "executions": len(histories),
        "continues": len(c),
        "restored_identically": m["restored"],
        "replayed": replayed,
        "events": m["events"],
        "history_bytes": m["history_bytes"],
        "peak_open": max((p.get("peak_open", 0) for p in peaks), default=0),
        "peak_reserved": max((p.get("peak_reserved", 0) for p in peaks), default=0),
        "reserved_opens": sum(p.get("reserved_opens", 0) for p in peaks),
        "cap": OPEN_SCOPES_CAP,
        "snapshot_max": SNAPSHOT_BYTES,
        "worst": worst,
    }
    with OUT.open("a") as f:
        f.write(json.dumps(out) + "\n")
    return out


async def main() -> None:
    for name in sys.argv[1:]:
        out = await run(name)
        w = out["worst"]
        print(
            f"=== {name} [{out['server']}]: {out['status']} in {out['elapsed_s']}s; {out['nodes']} nodes; "
            f"{out['executions']} executions, {out['continues']} continues ({out['restored_identically']} restored "
            f"identically), {out['replayed']} replayed; peak open {out['peak_open']} (reserved {out['peak_reserved']}); "
            f"worst encoded input {w.get('encoded', 0)} B of {SNAPSHOT_BYTES}; history {out['events']} events, "
            f"{out['history_bytes']} B",
            flush=True,
        )
        print("    worst parts:", {k: v for k, v in w.items() if v}, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
