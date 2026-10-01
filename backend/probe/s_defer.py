"""Throwaway (2b-1b §5.3 follow-up, scheduler alone, no Temporal): deferred loop steps, the shared budget request and
readiness-time variable captures. Drives each workload to completion in several orders, with snapshot round trips,
and checks at every turn:
- started loops inside iteration scopes never above OPEN_SCOPES_CAP_v + D (the §11.2 counterexample 4 made 21,611);
- the budget's waiting needs never above the started loops (queued loop steps add none);
- no loop step inside an iteration starts while the budget waits (it never fails early);
- a queued loop step reads the variables as they were when it became ready;
- every loop step starts or settles: the run completes.
Run from the proto's backend/:  .venv/bin/python <this file> [workload ...]"""

import json
import random
import sys
import time
from typing import Any

from dewpoint.engine.runtime.budget import Budget
from dewpoint.engine.runtime.scheduler import ITERATION_CAP_EXCEEDED, Instance, Scheduler
from tests.engine.runtime.support import program
from tests.support.graphs import G, ref

LOOP = "flow.loop@1"
SETV = "flow.set_variables@1"


def size(v: Any) -> int:
    return len(json.dumps(v, separators=(",", ":")))


def body_siblings(k: int = 240, *, outer: int = 10, mid: int = 10, n: int = 3, on_error: str = "fail", setvars: int = 0) -> G:
    """Nested outer x mid loops (concurrency 10 each), their body `k` sibling loops of `n` items with one step each,
    and a root chain of `setvars` set_variables steps: 2 + 2k + setvars nodes."""
    g = G()
    g.node("o", LOOP, {"items": list(range(outer)), "concurrency": 10, "collect": ref("item")}, on_error=on_error)
    g.node("m", LOOP, {"items": list(range(mid)), "concurrency": 10, "collect": ref("item")}, on_error=on_error)
    g.edge("o", "m", "body")
    for j in range(k):
        g.node(f"s{j}", LOOP, {"items": list(range(n)), "concurrency": 1, "collect": ref("item")}, on_error=on_error)
        g.node(f"x{j}", "testkit.echo@1", {"value": ref("item")})
        g.edge("m", f"s{j}", "body").edge(f"s{j}", f"x{j}", "body")
    if setvars:
        g.settings = {"vars_schema": {"type": "object", "properties": {f"k{v}": {"type": "integer", "default": -1} for v in range(setvars)}}}
    for v in range(setvars):
        g.node(f"v{v}", SETV, {"assignments": {f"k{v}": v}})
        if v:
            g.edge(f"v{v - 1}", f"v{v}")
    return g


def small(conc: int = 3, setvars: int = 3) -> G:
    """A root loop of `conc` items opening every iteration at once, each iteration a queued loop step, beside a root
    chain of set_variables steps: for comparing reads under a small cap and a cap that never defers."""
    g = G()
    g.node("l", LOOP, {"items": list(range(conc)), "concurrency": conc, "collect": ref("item")})
    g.node("q", LOOP, {"items": [0, 1], "concurrency": 1, "collect": ref("item")})
    g.node("x", "testkit.echo@1", {"value": ref("item")})
    g.edge("l", "q", "body").edge("q", "x", "body")
    g.settings = {"vars_schema": {"type": "object", "properties": {f"k{v}": {"type": "integer", "default": -1} for v in range(setvars)}}}
    for v in range(setvars):
        g.node(f"v{v}", SETV, {"assignments": {f"k{v}": v}})
        if v:
            g.edge(f"v{v - 1}", f"v{v}")
    return g


def drive(
    g: G,
    *,
    seed: int,
    order: str,
    snapshot_every: float,
    budget: Budget | None = None,
    pool: int = 0,
    ask_delay: int = 0,
    cap: int | None = None,
    max_steps: int = 20_000_000,
) -> dict[str, Any]:
    rng = random.Random(seed)
    prog = program(g)
    s = Scheduler(prog, budget=budget)
    if cap is not None:
        s.cap = cap
    schema = prog.graph.settings.vars_schema
    s.init_vars({k: p.get("default") for k, p in sorted(schema.get("properties", {}).items())})
    s.start()
    root_loops = sum(1 for st in prog.steps.values() if st.id in prog.regions and st.region is None)
    running: list[Instance] = []
    collects: list[Any] = []
    expect: dict[Instance, dict[str, Any]] = {}  # a queued loop step inside an iteration: the variables at readiness
    reads: dict[str, dict[str, Any]] = {}  # instance name -> what it read
    st = {"turns": 0, "restores": 0, "worst_bytes": 0, "loops_peak": 0, "needs_peak": 0, "asks": 0, "grants": 0,
          "cap_fails": 0, "iter_loop_starts": 0, "reads_checked": 0, "stale_vs_start": 0, "deltas_peak": 0,
          "deltas_bytes_peak": 0, "blocked_turns": 0}
    ask: list[Any] | None = None  # [Ask, due turn]
    parent = [pool]

    def note_ready() -> None:
        for inst in s._ready:  # everything queued since the last take: it became ready now
            if inst not in expect and s._iter_loop(inst):
                expect[inst] = dict(s.vars)

    def settle_spills() -> None:  # the store writes each claim at once
        for sp in s.take_spills():
            s.spilled(sp.loop, sp.which, sp.first, size(sp.pairs))

    def settle_budget() -> None:
        nonlocal ask
        others, new = s.answer_budget()
        assert not others, others
        if new is not None:
            assert ask is None, "a budget asks at most once at a time"
            ask = [new, st["turns"] + ask_delay]
            st["asks"] += 1
        note_ready()

    def count_settled() -> None:
        for _, out in s.take_settled():
            err = out.get("error") if isinstance(out, dict) else None
            if err and err.get("code") == ITERATION_CAP_EXCEEDED:
                st["cap_fails"] += 1

    note_ready()
    settle_budget()
    while s.ended is None:
        st["turns"] += 1
        if st["turns"] > max_steps:
            raise AssertionError("too many turns")
        s.take_cancels()
        iter_loops = sum(1 for i in s.loops if i.scope != ())
        st["loops_peak"] = max(st["loops_peak"], iter_loops)
        assert iter_loops <= s.cap + s.reserve, f"{iter_loops} started loops in iterations, past {s.cap} + {s.reserve}"
        st["needs_peak"] = max(st["needs_peak"], len(s.budget.waiting))
        assert len(s.budget.waiting) <= iter_loops + root_loops, "queued loop steps added needs"
        st["deltas_peak"] = max(st["deltas_peak"], len(s.undo))
        st["deltas_bytes_peak"] = max(st["deltas_bytes_peak"], sum(u.bytes() for u in s.undo.values()))
        if rng.random() < snapshot_every and not running and not collects and ask is None and not s.budget.waiting:
            count_settled()
            for inst in expect:  # each is still queued, or its scope ended (a failed iteration drops its queue)
                sc = s.scopes.get(inst.scope)
                assert inst in s._deferred or inst in s._ready or sc is None or sc.failure is not None, inst
            snap = json.loads(json.dumps(s.to_json()))
            st["worst_bytes"] = max(st["worst_bytes"], size(snap))
            restored = Scheduler.from_json(prog, snap)
            if cap is not None:
                restored.cap = cap
            again = json.loads(json.dumps(restored.to_json()))
            assert again == snap, "a restore doesn't re-encode identically"
            s = restored
            st["restores"] += 1
        blocked = bool(s.budget.waiting or s.budget.asking)
        got = s.take_ready()
        if blocked:
            st["blocked_turns"] += 1
            assert not any(s._iter_loop(i) for i in got), "a queued loop step started while the budget waits"
        running += got
        collects += s.take_collects()
        assert not s.take_batches(), "no batches here"
        count_settled()
        if ask is not None and (st["turns"] >= ask[1] or (not running and not collects)):
            a = ask[0]
            granted = min(a.want, parent[0]) if parent[0] >= a.need else 0
            parent[0] -= granted
            st["grants"] += bool(granted)
            ask = None
            s.budget.answered(granted)
            settle_budget()
            continue
        if not running and not collects:
            raise AssertionError(f"stuck: {s.open_scopes} open, {len(s._deferred)} deferred, budget {s.budget}")
        pool_n = len(running) + len(collects)
        if order == "loops_first":
            loops = [n for n, r in enumerate(running) if s.step(r).ref == LOOP]
            pick = loops[0] if loops else (len(running) if collects else rng.randrange(len(running)))
        elif order == "setvars_first":  # root writes settle as soon as they can, while loop steps are queued
            setv = [n for n, r in enumerate(running) if s.step(r).ref == SETV]
            pick = setv[0] if setv else rng.randrange(pool_n)
        else:
            pick = {"random": rng.randrange(pool_n), "newest": pool_n - 1, "oldest": 0}[order]
        if pick >= len(running):
            c = collects.pop(pick - len(running))
            s.collected(c.loop, c.index, c.index)
        else:
            inst = running.pop(pick)
            step = s.step(inst)
            if step.ref == LOOP:
                captured = s.consume_capture(inst)
                if s._iter_loop(inst):
                    st["iter_loop_starts"] += 1
                    assert captured is not None, "a loop step inside an iteration captured nothing"
                    assert captured == expect.pop(inst), "it read other variables than at readiness"
                    st["reads_checked"] += 1
                    st["stale_vs_start"] += captured != s.vars
                    reads["/".join(f"{k}:{i}" for k, i in inst.scope) + "/" + step.key] = captured
                s.open_loop(inst, list(step.config["items"]), concurrency=int(step.config["concurrency"]), stop_on_error=False)
            elif step.ref == SETV:
                s.set_variables(step.config["assignments"], inst)
                s.succeed(inst, {})
            else:
                s.succeed(inst, {"n": 1})
        settle_spills()
        note_ready()
        settle_budget()
    count_settled()
    assert s.ended.status == "succeeded", s.ended
    st["dropped_with_scope"] = len(expect)  # their iteration ended first (its loop stopped at the cap)
    return {"iterations": s.iterations, "cap": s.cap, "D": s.reserve, **st, **s.probe, "_reads": reads}


WORKLOADS: dict[str, Any] = {
    # §11.2 counterexample 4: 240 sibling loops in the body of nested 10 x 10 loops (482 nodes)
    "cap_siblings": lambda order, seed: drive(body_siblings(240), seed=seed, order=order, snapshot_every=0.001),
    # an exhausted root budget: 110 iterations for o and m, then 500 more, and 24,000 sibling loop steps
    "exhausted_root": lambda order, seed: drive(
        body_siblings(240, on_error="continue"), seed=seed, order=order, snapshot_every=0.2,
        budget=Budget(610, root=True)),
    # an exhausted child budget: it starts with 0 and asks its parent, which answers 5 turns later, with 610 in all
    "exhausted_child": lambda order, seed: drive(
        body_siblings(240, on_error="continue"), seed=seed, order=order, snapshot_every=0.2,
        budget=Budget(0, root=False), pool=610, ask_delay=5),
    # root set_variables settling while loop steps are queued (492 nodes)
    "vars_queued": lambda order, seed: drive(
        body_siblings(240, setvars=10), seed=seed, order=order, snapshot_every=0.001),
}


def invariance() -> dict[str, Any]:
    """The same run under a cap of 3 and a cap that never defers: the queued loop steps read the same values."""
    out = {}
    for order in ("setvars_first", "random", "oldest", "newest"):
        a = drive(small(), seed=3, order=order, snapshot_every=0.1, cap=3)
        b = drive(small(), seed=3, order=order, snapshot_every=0.1, cap=10_000)
        assert a["_reads"] == b["_reads"], (order, a["_reads"], b["_reads"])
        out[order] = {"reads": len(a["_reads"]), "deferred_peak_cap3": a.get("deferred_peak", 0),
                      "deferred_peak_big": b.get("deferred_peak", 0), "stale_vs_start_cap3": a["stale_vs_start"]}
    return out


def main() -> None:
    names = sys.argv[1:] or [*WORKLOADS, "invariance"]
    for name in names:
        if name == "invariance":
            print(f"invariance {invariance()}", flush=True)
            continue
        for order in ("random", "loops_first", "newest", "setvars_first" if name == "vars_queued" else "oldest"):
            t0 = time.monotonic()
            out = WORKLOADS[name](order, 7)
            out.pop("_reads")
            print(f"{name:16} {order:13} {time.monotonic() - t0:6.1f}s {out}", flush=True)


if __name__ == "__main__":
    main()
