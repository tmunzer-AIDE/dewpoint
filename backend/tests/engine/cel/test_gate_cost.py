# SPDX-License-Identifier: Apache-2.0
"""Gate 7 (spec §5.9), in-process half: latency per local evaluation at the caps, and the CPU a workflow task spends
on local evaluations between two yield points. The workflow-task half (the same load inside RunGraph, against
Temporal's timeout) runs in 2a-3. Results go to $DEWPOINT_CEL_GATE_RESULTS/cost.json when set, to tune the
thresholds."""

import json
import os
import statistics
import time
from collections.abc import Callable
from typing import Any

from dewpoint.engine.cel import bind, caps, evaluate, route
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from tests.engine.cel.support import make_record


def _ab(i: int) -> str:
    """320 characters of a and b, varied enough that an automaton for `a.......c` keeps finding new states."""
    return "".join("ab"[(i * 320 + j) * 2654435761 >> 20 & 1] for j in range(320))


AT_CAPS: dict[str, Any] = {
    "events": [
        {"mac": f"5c5b35{i:06x}", "type": "AP_DISCONNECTED" if i % 2 else "AP_CONNECTED"}
        for i in range(caps.LIST_LENGTH)
    ],
    "m": {f"k{i:03d}": i for i in range(caps.MAP_ENTRIES)},
    "s": "a" * caps.STRING_BYTES,
    # Worst cases within the caps for the adversarial loads below (each load reads only its own):
    "needle": "a" * (caps.STRING_BYTES // 2 - 1) + "b",  # searched in s: half the needle compared at every position
    "texts": [_ab(i) for i in range(caps.LIST_LENGTH)],  # scanned by a pattern like a.......c
    "c1": [[0] * caps.LIST_LENGTH for _ in range(80)],  # the most nodes two values within the caps can hold
    "c2": [[0] * caps.LIST_LENGTH for _ in range(79)] + [[0] * (caps.LIST_LENGTH - 1) + [1]],
    "dense": {f"k{i:03d}": [0] * 150 for i in range(caps.MAP_ENTRIES)},  # the most nodes a map at the cap can hold
}
WORST = [
    "trigger.events.filter(e, e.type == 'AP_DISCONNECTED').map(e, e.mac)",
    "sortedKeys(trigger.m).map(k, size(k) * 2)",  # static paths: a computed key runs in the evaluator (2b §4.1)
    "trigger.events.exists(e, e.mac.matches('^5c5b35[0-9a-f]{6}$')) && trigger.s.matches('^a+$')",
    "trigger.events.map(e, macOui(e.mac))",
]
P99_CEILING_S = 0.2  # a regression tripwire; the recorded measurements are what tune the thresholds
TASK_CPU_TARGET_S = 1.0  # spec §5.6: worst-case CPU per workflow task, against Temporal's 10 s timeout


def _view() -> Any:
    from tests.engine.cel.test_bind import view

    return view(trigger=AT_CAPS)


def test_local_latency_and_the_cpu_between_two_yield_points() -> None:
    records = [make_record(e, {"trigger.events": "list<map<string, dyn>>"}) for e in WORST]
    assert all(r.mode == "local" for r in records), [r.reason for r in records]
    v = _view()
    report: dict[str, Any] = {"profile": CURRENT_CEL_PROFILE, "latency": {}}
    for r in records:
        samples = []
        for _ in range(50):
            started = time.perf_counter()
            assert evaluate.evaluate_local(r, v).ok
            samples.append(time.perf_counter() - started)
        p99 = statistics.quantiles(samples, n=100, method="inclusive")[98]
        report["latency"][r.expr] = {"p99_s": p99, "max_s": max(samples)}
        assert p99 <= P99_CEILING_S, (r.expr, p99)
    report["task"] = {"mixed": _task(records, v)}
    for name, template in ADVERSARIAL.items():
        heaviest = _heaviest_local(template, v)
        report["task"][name] = {"expr_chars": len(heaviest.expr), "work": heaviest.work, **_task([heaviest], v)}
    binding = make_record(BINDING)
    assert binding.mode == "local" and bind.measure(bind.bind(binding, v)).within_caps
    report["task"]["binding"] = {"nodes": bind.measure(bind.bind(binding, v)).nodes, **_task([binding], v)}
    if directory := os.environ.get("DEWPOINT_CEL_GATE_RESULTS"):
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "cost.json"), "w") as f:
            json.dump(report, f, indent=1, sort_keys=True)
    for name, task in report["task"].items():
        assert task["cpu_s"] <= TASK_CPU_TARGET_S, (name, task)


def _task(records: list[Any], v: Any) -> dict[str, Any]:
    """Bind and evaluate back to back, cycling through `records`, until the yield policy demands a yield: what
    RunGraph does in one workflow task (execution.py, `_cel_task` and `_evaluate`)."""
    budget, cpu, done = route.YieldBudget(), time.process_time(), 0
    while not budget.must_yield():
        r = records[done % len(records)]
        bindings = bind.bind(r, v)
        budget.charge(nodes=bind.measure(bindings).nodes)
        if budget.must_yield(r):
            break
        evaluate.run(evaluate.compiled(r.expr, r.declarations), bindings)
        budget.charge(r)
        done += 1
    return {"evaluations": done, "cpu_s": time.process_time() - cpu}


def _per_event(body: str, n: int) -> str:
    return "trigger.events.exists(e, " + " || ".join([body] * n) + ")"


def _times(body: str, n: int) -> str:
    return "[" + ", ".join(["0"] * n) + "].exists(i, " + body + ")"


# One load per cost the work bound charges, each at its heaviest local form (spec §5.5): what the yield policy must
# keep within a task's CPU target.
ADVERSARIAL: dict[str, Callable[[int], str]] = {
    "python_calls": lambda n: _per_event("macOui(e.mac) == 'x'", n),  # Python-implemented calls per item
    "text": lambda n: _per_event("size(trigger.s + '' + trigger.s) == 0", n),  # copying strings at the cap
    "search": lambda n: _times("trigger.s.contains(trigger.needle)", n),  # substring search, text x needle
    "regex": lambda n: "trigger.texts.exists(t, t.matches('a" + "." * n + "c'))",  # pattern size x text
    "equality": lambda n: _times("trigger.c1 == trigger.c2", n),  # lists compared node by node
    "conversion": lambda n: _times("size(sortedKeys(trigger.dense)) == 0", n),  # a map converted for Python
}


# Cheap by its stored bounds, but binding the most values the caps allow: the cost the budget charges by `nodes`.
BINDING = "size(trigger.c1) + size(trigger.c2) >= 0"


def _heaviest_local(template: Callable[[int], str], v: Any) -> Any:
    """The largest n that still classifies local: it maxes out the work bound (or the expression or pattern
    length). Its inputs are within the caps and it evaluates, so the load is real."""
    best = None
    for n in range(1, 400):
        r = make_record(template(n), {"trigger.events": "list<map<string, dyn>>"})
        if r.mode != "local":
            break
        best = r
    assert best is not None, template(1)
    assert bind.measure(bind.bind(best, v)).within_caps, best.expr[:80]
    assert evaluate.evaluate_local(best, v).ok, best.expr[:80]
    return best
