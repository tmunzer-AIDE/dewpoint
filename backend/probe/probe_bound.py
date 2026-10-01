"""Throwaway (2b-1b §5.3 follow-up, rev 5): runs the follow-up's workloads on Temporal against the focused prototype
(branch proto/2b1b-bound), with its stub store on postgres:16-alpine, and checks at every continue of every execution:
- each component against its computed maximum (bounds.py): the envelope (ENVELOPE_MAX), the trigger (TRIGGER_MAX), no
  learned sensitive values, the structure (STRUCTURE_MAX_v(cap)), the live values (LIVE_BUDGET, recounted);
- the whole encoded continued input against SNAPSHOT_MAX;
- open scopes and started loops in iterations within cap + D, and the budget's waiting needs within the started loops;
- each snapshot restores and encodes again identically; every history replays; the run completes, with the values
  its outputs read (queued loop steps' reads included) as expected.
Publish (MemoryStore.add) computes the version's cap and D with bounds.py and pins them in the version.
Run from the proto's backend/:  PYTHONPATH=.:../../exp .venv/bin/python ../../exp/probe_bound.py <workload> [...]"""

import asyncio
import contextlib
import json
import os
import pathlib
import sys
import time
import uuid
from dataclasses import replace
from typing import Any

from temporalio.api.enums.v1 import EventType
from testcontainers.postgres import PostgresContainer

import bounds
import probe_run as R
from dewpoint.apps.worker import probe_store
from dewpoint.apps.worker.probe_store import ProbeStore, claim_envelope
from dewpoint.engine.runtime import probe as P
from dewpoint.engine.runtime.activities import RunInput
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.program import compile_program
from dewpoint.engine.runtime.scheduler import Scheduler
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.worker.harness import ENGINE_QUEUE, TENANT, MemoryStore
from tests.engine.replay.record import executions
from tests.support.graphs import G, ref
from tests.support.keys import opened

TIMEOUT_S = int(os.environ.get("PROBE_TIMEOUT", "2400"))
OUT = pathlib.Path(__file__).with_name("results_bound.jsonl")
LOOP, ECHO, SETV, DELAY, SUB = "flow.loop@1", "testkit.echo@1", "flow.set_variables@1", "flow.delay@1", "flow.run_workflow@1"
CAPS: dict[str, dict[str, Any]] = {}  # version id -> what publish computed
FORCE_CAP: list[int] = []

# --- publish: the version's cap and D, computed and pinned ------------------------------------------------------------

_add = MemoryStore.add


def _program(v: Any) -> Any:
    return compile_program(
        v.graph, v.manifests, v.expressions, v.cel_profile, v.subflow_version_ids, v.failure_handler_version_id,
        v.open_scopes_cap, v.loop_depth,
    )  # fmt: skip


def _publish(self: MemoryStore, g: G, workflow_id: Any = None, **kw: Any) -> str:
    vid = _add(self, g, workflow_id, **kw)
    v = self.versions[vid]
    m = bounds.maxima(_program(v))
    cap, formula = m.cap(True), "at_continue"  # the owner accepted the term in principle; the invariant is enforced
    if FORCE_CAP:
        cap, formula = FORCE_CAP[0], "forced"
    self.versions[vid] = replace(v, open_scopes_cap=cap, loop_depth=m.d)
    CAPS[vid] = {"cap": cap, "formula": formula, "m": m, "report": bounds.report(_program(v))}
    return vid


MemoryStore.add = _publish  # type: ignore[method-assign]


# --- workloads -------------------------------------------------------------------------------------------------------


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": outputs}
    return g


def loop(g: G, key: str, items: Any, conc: int = 10, collect: Any = None, **opts: Any) -> None:
    g.node(key, LOOP, {"items": items, "concurrency": conc, "collect": collect or ref("item")}, **opts)


L1, L2 = "a" * 200, "b" * 200  # 400 characters of keys: a pointer past POINTER_MAX


def rd(path: str) -> dict[str, Any]:
    """A reference to an optional field: publish asks for a default (it never applies to a handle, in the proto)."""
    return ref(path, default="<missing>")


def near_limit_trigger() -> tuple[G, dict[str, Any], dict[str, Any]]:
    """A trigger near the 1.75 MiB start limit: claimed down to its envelope before the run starts. Steps read a
    claimed subtree, and a value behind two 200-character keys (the reference derives a claim); a 2,000-iteration
    loop makes the run continue many times."""
    blob = {f"p{i}": f"{i:04d}" + "x" * 59_996 for i in range(28)}
    trigger = {"blob": blob, "deep": {L1: {L2: {"v": "deep-value", "fill": "y" * 70_000}}}}
    g = graph(p3=ref("steps.e1.output.value"), deep=ref("steps.e2.output.value"), n=ref("steps.l.output.count"))
    g.node("e1", ECHO, {"value": rd("trigger.blob.p3")})
    g.node("e2", ECHO, {"value": rd(f"trigger.deep.{L1}.{L2}.v")})
    loop(g, "l", list(range(2_000)))
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    return g, trigger, {"p3": blob["p3"], "deep": "deep-value", "n": 2_000}


def all_containers() -> tuple[G, dict[str, Any], dict[str, Any]]:
    """Every container of component 5 together. The root: 12 variables of 60 KB (720 KB, set by two steps) and 10
    results of 60 KB (600 KB): past the budget, the variables are the largest and are claimed. Then a 1,000-item loop
    in 10 batches whose body reads all 10 results (each batch's frozen results, 600 KB) and a variable, with 40 KB
    results per open iteration, collected: past the budget in each batch, the frozen results are claimed."""
    blobs = {f"b{i}": {"big": f"{i}" + "x" * 59_999, "small": i} for i in range(10)}
    g = graph(n=ref("steps.l.output.count"), at=rd("steps.last.output.value"), k11=rd("vars.k11"))
    g.settings["vars_schema"] = {
        "type": "object", "properties": {f"k{j}": {"type": "string", "default": ""} for j in range(12)},
    }  # fmt: skip
    for i in range(10):
        g.node(f"g{i}", ECHO, {"value": rd(f"trigger.blobs.b{i}")})
    g.node("v0", SETV, {"assignments": {f"k{j}": f"{j:02d}" + "v" * 59_998 for j in range(6)}})
    g.node("v1", SETV, {"assignments": {f"k{j}": f"{j:02d}" + "v" * 59_998 for j in range(6, 12)}}).edge("v0", "v1")
    for i in range(10):  # the variables are written once the results are in
        g.edge(f"g{i}", "v0")
    loop(g, "l", list(range(1_000)), collect=rd("steps.x.output"))
    g.edge("v1", "l")
    value = {"i": ref("item"), "pad": "p" * 40_000}  # 40 KB echoed: inline, so the open iterations press the budget
    value.update({f"s{i}": rd(f"steps.g{i}.output.value.small") for i in range(10)})
    g.node("x", ECHO, {"value": value}).edge("l", "x", "body")
    g.node("last", ECHO, {"value": rd("steps.l.output.items[123].value.i")}).edge("l", "last", "done")
    return g, {"blobs": blobs}, {"n": 1_000, "at": 123, "k11": "11" + "v" * 59_998}


def index_growth() -> tuple[G, dict[str, Any], dict[str, Any]]:
    """Collections whose segment lists grow past the budget: six root loops of 10,000 items collecting 1 KB each,
    with segments of 1 KiB (a stress knob: a tail claimed under pressure is that small), so each list holds
    ~10,000 entries and they're claimed as index segments; a step then reads through an index chain."""
    g = graph(n=ref("steps.l0.output.count"), at=rd("steps.last.output.value"))
    for j in range(6):
        loop(g, f"l{j}", list(range(10_000)), collect=ref("steps.c{j}.output".replace("{j}", str(j))))
        g.node(f"c{j}", ECHO, {"value": {"i": ref("item"), "pad": "c" * 1_000}}).edge(f"l{j}", f"c{j}", "body")
    g.node("last", ECHO, {"value": rd("steps.l3.output.items[7777].value.i")})
    for j in range(6):
        g.edge(f"l{j}", "last", "done")
    return g, {}, {"n": 10_000, "at": 7777}


def body_siblings(k: int, n: int, *, on_error: str = "fail", setvars: int = 0) -> G:
    """Nested 10 x 10 loops, their body k sibling loops of n items (one step each); with `setvars`, a root chain of
    set_variables steps with 1 s delays between them, and each sibling loop's items read a variable."""
    g = graph(n=rd("steps.o.output.count") if on_error != "fail" else ref("steps.o.output.count"))
    loop(g, "o", list(range(10)), on_error=on_error)
    loop(g, "m", list(range(10)), on_error=on_error)
    g.edge("o", "m", "body")
    for j in range(k):
        items: Any = [ref(f"vars.k{j % setvars}"), *range(n - 1)] if setvars else list(range(n))
        loop(g, f"s{j}", items, conc=1, on_error=on_error)
        g.node(f"x{j}", ECHO, {"value": ref("item")})
        g.edge("m", f"s{j}", "body").edge(f"s{j}", f"x{j}", "body")
    if setvars:
        g.settings["vars_schema"] = {
            "type": "object", "properties": {f"k{v}": {"type": "integer", "default": -1} for v in range(setvars)},
        }  # fmt: skip
    for v in range(setvars):
        g.node(f"v{v}", SETV, {"assignments": {f"k{v}": v}})
        if v:
            g.node(f"d{v}", DELAY, {"duration_s": 1}).edge(f"v{v - 1}", f"d{v}").edge(f"d{v}", f"v{v}")
    return g


def many_siblings() -> tuple[G, dict[str, Any], dict[str, Any]]:
    """§11.2's counterexample 4 on Temporal: 240 sibling loops in the body of nested 10 x 10 loops (482 nodes)."""
    return body_siblings(240, 2), {}, {"n": 10}


def vars_queued() -> tuple[G, dict[str, Any], dict[str, Any]]:
    """Root set_variables steps settling (1 s apart) while loop steps inside iterations are queued; each queued loop
    reads a variable (its captured version)."""
    return body_siblings(200, 2, setvars=9), {}, {"n": 10}


def small_vars() -> G:
    """Three iterations open at once, each a queued loop step reading three variables, beside a root chain writing
    them: under a cap of 3 two of them wait, under 100 none does. They must read the same."""
    g = graph(read=ref("steps.l.output.items"))
    g.settings["vars_schema"] = {
        "type": "object", "properties": {f"k{v}": {"type": "integer", "default": -1} for v in range(3)},
    }  # fmt: skip
    loop(g, "l", [0, 1, 2], conc=3, collect=ref("steps.q.output.items"))
    loop(g, "q", [ref("vars.k0"), ref("vars.k1"), ref("vars.k2")], conc=1)
    g.node("x", ECHO, {"value": ref("item")})
    g.edge("l", "q", "body").edge("q", "x", "body")
    for v in range(3):
        g.node(f"v{v}", SETV, {"assignments": {f"k{v}": 10 + v}})
        if v:
            g.edge(f"v{v - 1}", f"v{v}")
    g.edge("v0", "l")  # the iterations open once k0 is written; k1 and k2 are written while q waits
    return g


def exhausted_root() -> tuple[G, dict[str, Any], dict[str, Any]]:
    """An exhausted iteration budget (the root's cap lowered to 610), 24,000 queued sibling loop steps."""
    return body_siblings(240, 3, on_error="continue"), {}, {}


def exhausted_child(store: MemoryStore) -> tuple[G, dict[str, Any], dict[str, Any]]:
    """The same, as a sub-flow: its budget asks its parent (the root, capped at 610), which refuses once spent."""
    sub = store.publish(body_siblings(240, 3, on_error="continue"))
    g = graph(done=rd("steps.r.output.n"))
    g.node("r", SUB, {"workflow_id": str(sub), "input": {}}, on_error="continue")
    return g, {}, {}


def batch_slice(per: int) -> tuple[G, dict[str, Any], dict[str, Any]]:
    """A 101-item literal loop (two batches); with `per` characters an item, the first batch's slice is near the
    live-state budget (inline), or past it (the parent claims the list first, and slices are handles)."""
    g = graph(n=ref("steps.l.output.count"))
    loop(g, "l", [f"{i:04d}" + "z" * (per - 4) for i in range(101)], collect=ref("index"))
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    return g, {}, {"n": 101}


def refs() -> tuple[G, dict[str, Any], dict[str, Any]]:
    """References through long keys (a claimed trigger subtree, 400 characters of keys: a derived claim) and through
    chained handles (the root's claimed result set, whose entry holds a claimed output), and into a spilled
    collection (through its segments)."""
    trigger = {"deep": {L1: {L2: {"v": "deep-value", "fill": "y" * 70_000}}}}
    g = graph(deep=ref("steps.e2.output.value"), chained=ref("steps.e4.output.value"),
              coll=ref("steps.e5.output.value"))  # fmt: skip
    g.node("e2", ECHO, {"value": rd(f"trigger.deep.{L1}.{L2}.v")})
    g.node("big", ECHO, {"value": {"x": {"y": 42}, "pad": "z" * 70_000}})  # past 64 KiB: claimed by the activity
    for i in range(20):  # 1.2 MB of results: the root's result set is claimed
        g.node(f"f{i}", ECHO, {"value": f"{i}" + "f" * 59_999}).edge("big", f"f{i}")
    g.node("e4", ECHO, {"value": rd("steps.big.output.value.x.y")})
    for i in range(20):
        g.edge(f"f{i}", "e4")
    loop(g, "l", list(range(2_000)), collect=ref("steps.c.output"))
    g.node("c", ECHO, {"value": ref("item"), "pad": "c" * 1_000}).edge("l", "c", "body")
    g.edge("e4", "l")
    g.node("e5", ECHO, {"value": rd("steps.l.output.items[1234].value")}).edge("l", "e5", "done")
    return g, trigger, {"deep": "deep-value", "chained": 42, "coll": 1234}


def scope_items() -> tuple[G, dict[str, Any], dict[str, Any]]:
    """Open iterations whose items are 80 KB objects (a literal list of 12, 960 KB, within the budget): opening 10
    copies them into their scopes, and the list is claimed; each iteration then starts an inner loop over a 30 KB
    literal list, which is what passes the budget again: the largest containers are now the scopes' items. The inner
    steps read the outer item, through its handle once claimed."""
    items = [{"i": i, "pad": f"{i}" + "o" * 80_000} for i in range(12)]
    g = graph(n=ref("steps.o.output.count"), last=rd("steps.o.output.items[11]"))
    loop(g, "o", items, conc=10, collect=rd("loops.o.item.i"))
    loop(g, "inner", [{"j": j, "pad": "j" * 1_000} for j in range(30)], conc=1, collect=rd("steps.y.output.value"))
    g.node("y", ECHO, {"value": rd("loops.o.item.i")})
    g.edge("o", "inner", "body").edge("inner", "y", "body")
    return g, {}, {"n": 12, "last": 11}


def frozen_results() -> tuple[G, dict[str, Any], dict[str, Any]]:
    """A batch's frozen results claimed: 11 root results of 60 KB (660 KB) and a 101-item literal list of 3 KB items
    (303 KB) stay within the parent's budget; each batch holds the results its body reads and its 300 KB slice, and
    collecting its 3 KB items passes the budget: its largest container is then the frozen result set."""
    blobs = {f"b{i}": {"big": f"{i}" + "x" * 59_999, "small": i} for i in range(11)}
    g = graph(n=ref("steps.l.output.count"), at=rd("steps.l.output.items[57].i"))
    for i in range(11):
        g.node(f"g{i}", ECHO, {"value": rd(f"trigger.blobs.b{i}")})
    loop(g, "l", [{"i": i, "pad": "q" * 2_950} for i in range(101)], conc=10)
    for i in range(11):
        g.edge(f"g{i}", "l")
    value = {"i": rd("item.i"), **{f"s{i}": rd(f"steps.g{i}.output.value.small") for i in range(11)}}
    g.node("x", ECHO, {"value": value}).edge("l", "x", "body")
    return g, {"blobs": blobs}, {"n": 101, "at": 57}


WORKLOADS: dict[str, Any] = {
    "frozen_results": lambda s: frozen_results(),
    "scope_items": lambda s: scope_items(),
    "index_growth": lambda s: index_growth(),
    "near_limit_trigger": lambda s: near_limit_trigger(),
    "all_containers": lambda s: all_containers(),
    "many_siblings": lambda s: many_siblings(),
    "vars_queued": lambda s: vars_queued(),
    "exhausted_root": lambda s: exhausted_root(),
    "exhausted_child": exhausted_child,
    "batch_slice_inline": lambda s: batch_slice(9_600),
    "batch_slice_claimed": lambda s: batch_slice(10_800),
    "refs": lambda s: refs(),
}
ROOT_BUDGET = {"exhausted_root": 610, "exhausted_child": 610}
SEG_BYTES = {"index_growth": 1_024}  # a stress knob: small segments, as tails claimed under pressure are


# --- measurement ------------------------------------------------------------------------------------------------------


def _header(sj: dict[str, Any]) -> dict[str, Any]:
    empty = {"scopes": [], "loops": [], "handed": [], "collects_out": [], "batches_out": [], "spills_out": [],
             "budget_waits": [], "vars": {}, "undo": [], "released": [], "starting": [], "held": []}  # fmt: skip
    budget = {**sj["budget"], "reserved": {}, "waiting": []}
    return {**sj, **empty, "budget": budget, "vbox": [None, None, sj["vbox"][2]]}


async def measure(histories: list[Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    violations: list[str] = []
    programs: dict[str, Any] = {}
    seen = 0
    for h in histories:
        for e in h.events:
            if e.event_type != EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW:
                continue
            seen += 1
            full = seen % CHECK_EVERY == 1 or CHECK_EVERY == 1  # restore-check every k-th; sizes for every one
            [payload] = e.workflow_execution_continued_as_new_event_attributes.input.payloads
            inp = await opened(payload)
            vid = inp["version_id"]
            info = CAPS[vid]
            m: bounds.Maxima = info["m"]
            cap = info["cap"]
            if vid not in programs:
                v = STORE.versions[vid]
                programs[vid] = _program(v)
            snap = inp["snapshot"]
            sj = snap["scheduler"]
            sched = Scheduler.from_json(programs[vid], sj)
            if full:
                again = json.loads(json.dumps(sched.to_json()))
                if again != sj:
                    violations.append(f"{h.workflow_id}: a snapshot doesn't restore identically")
            live = sched.live
            recount = sched._recount()
            header = _header(sj)
            env_in = {**inp, "trigger": {}, "snapshot": {**snap, "scheduler": header, "timers": []}}
            envelope = bounds.encoded(env_in)
            structure = R.size(sj) - live - R.size(header) + R.size(snap["timers"])
            root = sched.batch_loop.scope if sched.batch_loop is not None else ()
            iter_loops = sum(1 for i in sched.loops if i.scope != root)
            row = {
                "workflow": h.workflow_id[-40:], "encoded": payload.ByteSize(), "envelope": envelope,
                "trigger": R.size(inp["trigger"]), "secrets": len(snap["secrets"]) + len(
                    (inp.get("parent") or {}).get("secrets") or []),
                "structure": structure, "structure_max": m.structure(cap, True), "live": live,
                "open": sched.open_scopes, "iter_loops": iter_loops, "needs": len(sched.budget.waiting),
                "grants": len(sched.budget.reserved), "deferred": len(sched._ready), "undo": len(sched.undo),
                "scope_failures": sum(1 for sc in sched.scopes.values() if sc.failure is not None),
            }  # fmt: skip
            checks = {
                "live==recount": live == recount,
                "envelope<=ENVELOPE_MAX": envelope <= m.envelope,
                "trigger<=TRIGGER_MAX": row["trigger"] <= m.trigger,
                "no secrets": row["secrets"] == 0,
                "structure<=STRUCTURE_MAX": structure <= m.structure(cap, True),
                "live<=LIVE_BUDGET": live <= P.LIVE_BUDGET,
                "encoded<=SNAPSHOT_MAX": row["encoded"] <= bounds.SNAPSHOT_MAX,
                "open<=cap+D": row["open"] <= cap + m.d,
                "iter_loops<=cap+D": iter_loops <= cap + m.d,
                "no waiting need at a continue": row["needs"] == 0 and not sj.get("budget_waits"),
                "no grant at a continue": row["grants"] == 0,
                "no failed scope kept": row["scope_failures"] == 0,
            }
            for name, ok in checks.items():
                if not ok:
                    violations.append(f"{h.workflow_id[-40:]}: {name} ({row})")
            rows.append(row)
    return {"rows": rows, "violations": violations}


def _longest_task_ms(histories: list[Any]) -> int:
    """The longest workflow task, started to completed (the SDK's deadlock detector allows 2 s without a yield)."""
    worst = 0
    for h in histories:
        started = None
        for e in h.events:
            if e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_STARTED:
                started = e.event_time.ToMilliseconds()
            elif e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_COMPLETED and started is not None:
                worst = max(worst, e.event_time.ToMilliseconds() - started)
                started = None
    return worst


def _activations() -> dict[str, Any]:
    """The run's own activations (recorded before the replay, which runs them again without the runner)."""
    import timing_runner

    out = timing_runner.summary()
    timing_runner.ACTIVATIONS.clear()
    return out


def _replay_sample(histories: list[Any]) -> list[Any]:
    """With REPLAY_SAMPLE, the first and last history and that many others, chosen with a fixed seed."""
    if not REPLAY_SAMPLE or len(histories) <= REPLAY_SAMPLE + 2:
        return histories
    import random

    middle = random.Random(7).sample(histories[1:-1], REPLAY_SAMPLE)
    return [histories[0], *middle, histories[-1]]


def _task_times(histories: list[Any]) -> list[int]:
    out = []
    for h in histories:
        started = None
        for e in h.events:
            if e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_STARTED:
                started = e.event_time.ToMilliseconds()
            elif e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_COMPLETED and started is not None:
                out.append(e.event_time.ToMilliseconds() - started)
                started = None
    return out


FAILED_TASKS: list[dict[str, Any]] = []  # each failed workflow task, with the events around it


def _task_failures(histories: list[Any]) -> dict[str, int]:
    """Failed workflow tasks, by cause (a deadlock, a nondeterminism, an unhandled command, ...). Each one's
    context goes to FAILED_TASKS: its cause, its time, and the events just before and after it (an unhandled command
    means an event arrived while the task completed: which one)."""
    from temporalio.api.enums.v1 import WorkflowTaskFailedCause

    out: dict[str, int] = {}
    for h in histories:
        events = list(h.events)
        for n, e in enumerate(events):
            if e.event_type != EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED:
                continue
            a = e.workflow_task_failed_event_attributes
            cause = WorkflowTaskFailedCause.Name(a.cause).removeprefix("WORKFLOW_TASK_FAILED_CAUSE_")
            kind = a.failure.application_failure_info.type or cause
            out[kind] = out.get(kind, 0) + 1
            around = [EventType.Name(x.event_type).removeprefix("EVENT_TYPE_") for x in events[max(0, n - 3) : n + 4]]
            FAILED_TASKS.append({"workflow": h.workflow_id[-24:], "kind": kind, "cause": cause,
                                 "at": e.event_time.ToJsonString(), "events": around})  # fmt: skip
    return out


def _activity_timeouts(histories: list[Any]) -> int:
    return sum(e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT for h in histories for e in h.events)


def _count_activities(histories: list[Any], name: str) -> int:
    n = 0
    for h in histories:
        for e in h.events:
            if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
                n += e.activity_task_scheduled_event_attributes.activity_type.name == name
    return n


async def start_run(client: Any, store: MemoryStore, g: G, trigger: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """As admission: publish, claim the trigger down to its envelope (§3.5), then start."""
    vid = store.add(g)
    run_id = str(uuid.uuid4())
    wid = run_workflow_id(TENANT, run_id)
    envelope = trigger
    if P.size(trigger) > P.TRIGGER_INLINE:
        assert probe_store.STORE is not None
        envelope = await claim_envelope(probe_store.STORE, trigger, f"{wid}/trigger", P.TRIGGER_INLINE)
    run = RunInput(TENANT, run_id, vid, envelope, checkpoint_events=300, drain_events=600)
    handle = await client.start_workflow(RunGraph.run, run, id=wid, task_queue=ENGINE_QUEUE)
    return handle, {"version": vid, "trigger_bytes": P.size(trigger), "envelope_bytes": P.size(envelope)}


STORE: MemoryStore = MemoryStore()


STOPPED: list[float] = []  # when the probe cancelled its copies (epoch seconds)
CONCURRENT = int(os.environ.get("CONCURRENT", "1"))  # copies of the workload started at once on one worker
SAMPLE_S = float(os.environ.get("SAMPLE_S", "0"))  # > 0: measure that long, then cancel the copies
STOP_AFTER = int(os.environ.get("STOP_AFTER", "0"))  # > 0: cancel each copy once it has continued this many times
CHECK_EVERY = int(os.environ.get("CHECK_EVERY", "1"))  # restore-check every k-th continue (CPU runs: bounds are known)
REPLAY_SAMPLE = int(os.environ.get("REPLAY_SAMPLE", "0"))  # > 0: replay the first, the last and this many others


async def run(name: str, url: str) -> dict[str, Any]:
    if CONCURRENT > 1 or SAMPLE_S > 0 or STOP_AFTER > 0:
        return await run_many(name, url, CONCURRENT, SAMPLE_S)
    return await run_one(name, url)


async def _stop_when_due(client: Any, handles: list[Any], sample_s: float) -> None:
    """With STOP_AFTER, once every copy has continued that many times (its latest run id changed as often), or with
    SAMPLE_S once that long has passed, cancel each copy's latest run by its workflow id, and say so if it fails."""
    if not STOP_AFTER and not sample_s:
        return
    started = time.monotonic()
    runs: dict[str, set[str]] = {h.id: set() for h in handles}
    while True:
        done = 0
        for h in handles:
            d = await client.get_workflow_handle(h.id).describe()
            runs[h.id].add(d.run_id)
            if d.status is not None and d.status.name != "RUNNING":
                done += 1
        continued = min(len(r) - 1 for r in runs.values())
        if done == len(handles):
            return
        if (STOP_AFTER and continued >= STOP_AFTER) or (sample_s and time.monotonic() - started >= sample_s):
            break
        await asyncio.sleep(2)
    STOPPED.append(time.time())
    print(f"    stopping after {continued} continues each, {time.monotonic() - started:.0f}s", flush=True)
    for h in handles:
        try:
            await client.get_workflow_handle(h.id).cancel()
        except Exception as e:  # loud: a cancel that didn't land means the copy runs on
            print(f"    CANCEL FAILED for {h.id[-12:]}: {type(e).__name__}: {e}", flush=True)


async def run_many(name: str, url: str, k: int, sample_s: float) -> dict[str, Any]:
    """K copies of a workload at once on one worker (the representative concurrency the CPU check asks for);
    with `sample_s`, they're cancelled after that long and what ran is measured and replayed."""
    FAILED_TASKS.clear()
    STOPPED.clear()
    global STORE
    probe_store.STORE = ProbeStore(url)
    STORE = MemoryStore()
    P.PEAKS.clear()
    P.TIMES.clear()
    P.ROOT_BUDGET[:] = [ROOT_BUDGET[name]] if name in ROOT_BUDGET else []
    P.SEG_BYTES = SEG_BYTES.get(name, 262_144)
    t0 = time.monotonic()
    statuses: list[str] = []
    async with await R.environment() as env:
        async with R.serve(env.client, STORE):
            handles = []
            for _ in range(k):
                g, trigger, _expected = WORKLOADS[name](STORE)
                handle, _admitted = await start_run(env.client, STORE, g, trigger)
                handles.append(handle)
            print(f"    {k} runs", [h.id[-12:] for h in handles], flush=True)
            await _stop_when_due(env.client, handles, sample_s)
            for h in handles:
                try:
                    statuses.append((await asyncio.wait_for(h.result(), TIMEOUT_S)).status)
                except Exception as e:
                    statuses.append(type(e).__name__)
            if any(s2 in ("TimeoutError",) for s2 in statuses):  # a cancelled root raises WorkflowFailureError
                print("    RUNS DIDN'T END AS EXPECTED:", statuses, flush=True)
            elapsed = time.monotonic() - t0
        histories = [x for h in handles for x in await executions(env.client, h.id, h.first_execution_run_id or "")]
    m = await measure(histories)
    run_times = {w: dict(t) for w, t in P.TIMES.items()}
    try:
        replayed: Any = await R.replay(_replay_sample(histories))
    except Exception as e:
        replayed = f"FAILED: {type(e).__name__}: {str(e)[:200]}"
    rows = m["rows"]
    worst = {k2: max((r[k2] for r in rows), default=0) for k2 in (rows[0] if rows else {}) if k2 != "workflow"}
    activations = _activations()
    out = {
        "workload": f"{name} x{k}" + (f" sampled {sample_s:.0f}s" if sample_s else "")
        + (f" slots {os.environ['WFT_SLOTS']}" if os.environ.get("WFT_SLOTS") else ""),
        "server": "linux-dev" if os.environ.get("TEMPORAL_ADDRESS") else ("dev" if os.environ.get("DEV") == "1" else "time-skipping"),
        "status": statuses, "error": None, "elapsed_s": round(elapsed, 1), "nodes": 0, "outputs_ok": None,
        "executions": len(histories), "continues": len(rows), "replayed": replayed,
        "violations": m["violations"][:10], "n_violations": len(m["violations"]), "cap": None, "cap_formula": None,
        "longest_task_ms": _longest_task_ms(histories), "task_ms": _dist(_task_times(histories)),
        "task_failures": _task_failures(histories), "activity_timeouts": _activity_timeouts(histories),
        "phase_ms": {ph: round(max(t.get(ph, 0.0) for t in run_times.values()), 1)
                     for ph in sorted({ph for t in run_times.values() for ph in t})},
        "activations": activations, "failed_task_context": list(FAILED_TASKS), "stopped_at": list(STOPPED),
        "probe": {c: sum(P.PEAKS.get(i, {}).get(c, 0) for i in {h.workflow_id for h in histories})
                  for c in ("cap_refused", "deferred_peak", "peak_open", "undo_peak")},
        "asks": 0, "container_spills_by": {"runs": {}, "batches": {}}, "worst": worst,
    }  # fmt: skip
    with OUT.open("a") as f:
        f.write(json.dumps(out, default=str) + "\n")
    return out


async def run_one(name: str, url: str) -> dict[str, Any]:
    FAILED_TASKS.clear()
    STOPPED.clear()
    global STORE
    probe_store.STORE = ProbeStore(url)
    STORE = MemoryStore()
    P.PEAKS.clear()
    P.TIMES.clear()
    P.ROOT_BUDGET[:] = [ROOT_BUDGET[name]] if name in ROOT_BUDGET else []
    P.SEG_BYTES = SEG_BYTES.get(name, 262_144)
    g, trigger, expected = WORKLOADS[name](STORE)
    status, error, outputs = "timeout", None, None
    t0 = time.monotonic()
    async with await R.environment() as env:
        async with R.serve(env.client, STORE):
            handle, admitted = await start_run(env.client, STORE, g, trigger)
            print("    run", handle.id, flush=True)
            try:
                result = await asyncio.wait_for(handle.result(), TIMEOUT_S)
                status, error, outputs = result.status, result.error, result.outputs
            except TimeoutError:
                pass
            elapsed = time.monotonic() - t0
        histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
    m = await measure(histories)
    run_times = {w: dict(t) for w, t in P.TIMES.items()}  # the run's own, before the replay adds its passes
    try:
        replayed: Any = await R.replay(_replay_sample(histories))
    except Exception as e:  # reported, not fatal: the other workloads still run
        replayed = f"FAILED: {type(e).__name__}: {str(e)[:200]}"
    resolved = await probe_store.STORE.resolve(outputs) if outputs is not None else None
    got = {k: resolved.get(k) for k in expected} if isinstance(resolved, dict) else None
    ids = {h.workflow_id for h in histories}
    peaks = [P.PEAKS.get(i, {}) for i in ids]
    activations = _activations()
    rows = m["rows"]
    worst = {k: max((r[k] for r in rows), default=0) for k in (rows[0] if rows else {}) if k != "workflow"}
    info = CAPS[admitted["version"]]
    counters = ("container_spills", "result_set_spills", "item_spills_scope", "vars_spills", "undo_spills",
                "index_spills", "spills", "item_spills", "result_spills", "derived", "input_claims", "undo_peak",
                "stale_vs_start", "cap_refused",
                "var_versions", "deferred_peak", "peak_open", "peak_reserved", "reserved_opens", "cap_waits")  # fmt: skip
    out = {
        "workload": name, "server": "dev" if os.environ.get("DEV") == "1" else "time-skipping",
        "nodes": len(g.nodes), "status": status, "error": error, "elapsed_s": round(elapsed, 1),
        "outputs_ok": got == expected if expected else None, "outputs": _short(got), "expected": _short(expected),
        "outputs_full": _short(resolved),
        "executions": len(histories), "continues": len(rows), "replayed": replayed,
        "violations": m["violations"][:10], "n_violations": len(m["violations"]),
        "cap": info["cap"], "cap_formula": info["formula"], "maxima": info["report"], **admitted,
        "probe": {c: (max if c.endswith(("peak", "open", "reserved", "versions")) else sum)(
            p.get(c, 0) for p in peaks) for c in counters},
        "container_spills_by": {
            kind: {c: sum(P.PEAKS.get(i, {}).get(c, 0) for i in ids if ("/batch:" in i) == (kind == "batches"))
                   for c in counters if c.endswith("spills") or c == "spills"}
            for kind in ("runs", "batches")
        },  # fmt: skip
        "asks": sum(1 for h in histories for e in h.events
                    if e.event_type == EventType.EVENT_TYPE_SIGNAL_EXTERNAL_WORKFLOW_EXECUTION_INITIATED),
        "derive_activities": _count_activities(histories, P.DERIVE),
        "longest_task_ms": _longest_task_ms(histories),
        "task_ms": _dist(_task_times(histories)),
        "task_failures": _task_failures(histories), "activity_timeouts": _activity_timeouts(histories),
        "activations": activations, "failed_task_context": list(FAILED_TASKS),
        "phase_ms": {ph: round(max(t.get(ph, 0.0) for t in run_times.values()), 1)
                     for ph in sorted({ph for t in run_times.values() for ph in t})},  # fmt: skip
        "events": sum(len(h.events) for h in histories), "worst": worst,
    }  # fmt: skip
    with OUT.open("a") as f:
        f.write(json.dumps(out, default=str) + "\n")
    return out


def _dist(xs: list[int]) -> dict[str, int]:
    if not xs:
        return {}
    xs = sorted(xs)
    return {"n": len(xs), "p50": xs[len(xs) // 2], "p99": xs[min(len(xs) - 1, len(xs) * 99 // 100)], "max": xs[-1],
            "over_500": sum(x > 500 for x in xs), "over_1000": sum(x > 1000 for x in xs)}  # fmt: skip


def _short(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _short(x) for k, x in v.items()}
    if isinstance(v, str) and len(v) > 40:
        return f"{v[:12]}…({len(v)} chars)"
    return v


async def main() -> None:
    external = os.environ.get("POSTGRES_URL")  # the Linux probe's postgres container
    with contextlib.nullcontext() if external else PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = external or pg.get_connection_url()
        await ProbeStore(url).setup()
        for name in sys.argv[1:]:
            if name == "vars_invariance":
                await invariance(url)
                continue
            if name == "cancel_race":
                await cancel_race(url)
                continue
            out = await run(name, url)
            w = out["worst"]
            print(
                f"=== {name} [{out['server']}]: {out['status']} in {out['elapsed_s']}s; {out['nodes']} nodes; cap "
                f"{out['cap']} ({out['cap_formula']}); outputs ok: {out['outputs_ok']}; {out['executions']} "
                f"executions, {out['continues']} continues, {out['replayed']} replayed; violations "
                f"{out['n_violations']}; worst encoded {w.get('encoded', 0)} B of {bounds.SNAPSHOT_MAX}; longest "
                f"workflow task {out['longest_task_ms']} ms",
                flush=True,
            )
            print("    worst:", w, flush=True)
            print("    probe:", {k: v for k, v in out["probe"].items() if v}, "asks:", out["asks"], flush=True)
            print("    phases (ms, longest):", out["phase_ms"], flush=True)
            print("    workflow tasks (ms):", out["task_ms"], "failed tasks:", out["task_failures"], flush=True)
            print("    activations (ms):", out.get("activations"), "activity timeouts:", out.get("activity_timeouts"),
                  flush=True)  # fmt: skip
            for f in out.get("failed_task_context") or []:
                print("    FAILED TASK:", f, "stopped at:", out.get("stopped_at"), flush=True)
            print("    spills by:", {k: {c: n for c, n in v.items() if n} for k, v in out["container_spills_by"].items()})
            for v in out["violations"]:
                print("    VIOLATION", v[:300], flush=True)
            if out["error"]:
                print("    error:", out["error"], flush=True)


def continuing(n: int = 100) -> G:
    """A run that continues as new every few workflow tasks (with checkpoint_events=60): a loop of 100 echo steps, run
    inline (no batch children)."""
    g = graph(n=ref("steps.l.output.count"))
    loop(g, "l", list(range(n)))
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    return g


async def cancel_race(url: str) -> None:
    """A controlled cancellation run (the `UnhandledCommand` question): N runs that continue as new every second or
    so, each cancelled at a random moment (seeded), and the same N never cancelled. For each failed workflow task: its
    cause, and whether a cancel request is the event that follows it in the history (an unhandled command means an
    event arrived while the task completed with a command that closes the run)."""
    import random

    from temporalio.api.enums.v1 import WorkflowTaskFailedCause

    n = int(os.environ.get("RACE_RUNS", "40"))
    rng = random.Random(int(os.environ.get("RACE_SEED", "7")))
    probe_store.STORE = ProbeStore(url)
    out: dict[str, Any] = {}
    for mode in ("cancelled", "control"):
        store = MemoryStore()
        async with await R.environment() as env:
            async with R.serve(env.client, store):
                handles = []
                for _ in range(n):
                    vid = store.add(continuing())
                    run_id = str(uuid.uuid4())
                    wid = run_workflow_id(TENANT, run_id)
                    run = RunInput(TENANT, run_id, vid, {}, checkpoint_events=60, drain_events=120)
                    handles.append(await env.client.start_workflow(RunGraph.run, run, id=wid, task_queue=ENGINE_QUEUE))
                if mode == "cancelled":
                    async def cancel_later(h: Any, delay: float) -> None:
                        await asyncio.sleep(delay)
                        try:
                            await env.client.get_workflow_handle(h.id).cancel()
                        except Exception as e:
                            print(f"    CANCEL FAILED {h.id[-8:]}: {type(e).__name__}", flush=True)

                    await asyncio.gather(*(cancel_later(h, rng.uniform(0.5, 12.0)) for h in handles))
                for h in handles:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(h.result(), 300)
                histories = [x for h in handles for x in await executions(env.client, h.id, h.first_execution_run_id or "")]
        failures: list[dict[str, Any]] = []
        continues = 0
        for h in histories:
            events = list(h.events)
            for i, e in enumerate(events):
                if e.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW:
                    continues += 1
                if e.event_type != EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED:
                    continue
                cause = WorkflowTaskFailedCause.Name(e.workflow_task_failed_event_attributes.cause)
                after = [EventType.Name(x.event_type).removeprefix("EVENT_TYPE_") for x in events[i + 1 : i + 3]]
                failures.append({"cause": cause.removeprefix("WORKFLOW_TASK_FAILED_CAUSE_"), "after": after,
                                 "cancel_next": "WORKFLOW_EXECUTION_CANCEL_REQUESTED" in after})  # fmt: skip
        out[mode] = {"runs": n, "executions": len(histories), "continues": continues, "failed_tasks": len(failures),
                     "by_cause": {c: sum(f["cause"] == c for f in failures) for c in {f["cause"] for f in failures}},
                     "unhandled_with_cancel_next": sum(f["cause"] == "UNHANDLED_COMMAND" and f["cancel_next"]
                                                       for f in failures),
                     "unhandled_without": sum(f["cause"] == "UNHANDLED_COMMAND" and not f["cancel_next"]
                                              for f in failures),
                     "examples": failures[:3]}  # fmt: skip
        print(f"=== cancel_race [{mode}]: {out[mode]}", flush=True)
    with OUT.open("a") as f:
        f.write(json.dumps({"workload": "cancel_race", "server": _server(), **out}, default=str) + "\n")


def _server() -> str:
    if os.environ.get("TEMPORAL_ADDRESS"):
        return "linux-dev"
    return "dev" if os.environ.get("DEV") == "1" else "time-skipping"


async def invariance(url: str) -> None:
    """The queued loop steps' reads, under a cap of 3 and of 100: the same."""
    reads = {}
    for cap in (3, 100):
        FORCE_CAP[:] = [cap]
        WORKLOADS["_small"] = lambda s: (small_vars(), {}, {})
        out = await run("_small", url)
        reads[cap] = (out["status"], out["outputs_full"], out["probe"].get("deferred_peak"),
                      out["probe"].get("stale_vs_start"))
    FORCE_CAP[:] = []
    same = reads[3][1] == reads[100][1]
    line = {"workload": "vars_invariance", "server": "dev" if os.environ.get("DEV") == "1" else "time-skipping",
            "same_reads": same, "cap3": reads[3], "cap100": reads[100]}  # fmt: skip
    with OUT.open("a") as f:
        f.write(json.dumps(line, default=str) + "\n")
    print(f"=== vars_invariance: same reads {same}: cap 3 {reads[3]}, cap 100 {reads[100]}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
