# SPDX-License-Identifier: Apache-2.0
"""Gate 7 (spec §5.9), in-process half: latency per local evaluation at the caps, and the CPU a workflow task spends
on local evaluations between two yield points. The workflow-task half (the same load inside RunGraph, against
Temporal's timeout) runs in 2a-3. Results go to $DEWPOINT_CEL_GATE_RESULTS when set, to tune the thresholds."""

import json
import os
import statistics
import time
from typing import Any

from dewpoint.engine.cel import caps, evaluate, route
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from tests.engine.cel.support import make_record

AT_CAPS: dict[str, Any] = {
    "events": [{"mac": f"5c5b35{i:06x}", "type": "AP_DISCONNECTED" if i % 2 else "AP_CONNECTED"} for i in range(1000)],
    "m": {f"k{i:03d}": i for i in range(caps.MAP_ENTRIES)},
    "s": "a" * 8_000,
}
WORST = [
    "trigger.events.filter(e, e.type == 'AP_DISCONNECTED').map(e, e.mac)",
    "sortedKeys(trigger.m).map(k, trigger.m[k] * 2)",
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
    report["task"] = {"mixed": _task(records, v), "adversarial": _task([_heaviest_local()], v)}
    if path := os.environ.get("DEWPOINT_CEL_GATE_RESULTS"):
        with open(path, "w") as f:
            json.dump(report, f, indent=1, sort_keys=True)
    for name, task in report["task"].items():
        assert task["cpu_s"] <= TASK_CPU_TARGET_S, (name, task)


def _task(records: list[Any], v: Any) -> dict[str, Any]:
    """Evaluate back to back, cycling through `records`, until the yield policy demands a yield."""
    budget, cpu, done = route.YieldBudget(), time.process_time(), 0
    while not budget.must_yield(r := records[done % len(records)]):
        evaluate.evaluate_local(r, v)
        budget.charge(r)
        done += 1
    return {"evaluations": done, "cpu_s": time.process_time() - cpu}


def _heaviest_local() -> Any:
    """The body with the most Python-implemented calls per element that still classifies local: it maxes out the
    work bound, which is what the yield policy must keep within a task's CPU target."""
    best = None
    for calls in range(10, 400, 10):
        body = " || ".join(["macOui(e.mac) == 'x'"] * calls)
        r = make_record(f"trigger.events.exists(e, {body})", {"trigger.events": "list<map<string, dyn>>"})
        if r.mode != "local":
            break
        best = r
    assert best is not None
    return best
