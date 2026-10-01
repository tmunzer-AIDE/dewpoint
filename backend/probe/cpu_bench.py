"""Throwaway (2b-1b §5.3 CPU check): the scheduler's structural work at the maximum measured, without Temporal. Builds
the state of 240 sibling loops in nested 10 x 10 loops with ~21,600 queued loop steps (calib.big), then times the
snapshot's and the restore's parts, and packs the parts into workflow tasks as the execution does (a part always runs
first in a task; past the task's share, the next part waits for the next task). Reports each task's time.
Run from the proto's backend/:  PYTHONPATH=.:../../exp .venv/bin/python ../../exp/cpu_bench.py [repeats]"""

import json
import platform
import sys
import time

import calib
from dewpoint.engine.cel.route import STARTUP_SHARE, YIELD_STRUCTURE
from dewpoint.engine.runtime.scheduler import Scheduler


def tasks(parts: list[tuple[int, float]], *, startup: bool) -> list[float]:
    """The parts' times grouped into workflow tasks by their units: the execution's own packing."""
    out, units, ms, share = [], 0, 0.0, STARTUP_SHARE if startup else 1
    for u, t in parts:
        if units and units + u > YIELD_STRUCTURE // share:
            out.append(ms)
            units, ms, share = 0, 0.0, 1
        units += u
        ms += t
    return out + [ms]


def main() -> None:
    repeats = int(sys.argv[1]) if sys.argv[1:] else 5
    s = calib.big()
    print(f"{platform.platform()}; {len(s._deferred)} queued loop steps, {len(s.scopes)} scopes", flush=True)
    worst: dict[str, float] = {}
    for _ in range(repeats):
        snap, enc = calib.parts(s.encoding(check=False))
        data = json.loads(json.dumps(snap))
        r = Scheduler.restoring(s.program, data)
        _, dec = calib.parts(r.decoding(data))
        t0 = time.perf_counter()
        r.take_ready()
        take = (time.perf_counter() - t0) * 1000
        row = {
            "encode_ms": sum(t for _, t in enc), "encode_task_max_ms": max(tasks(enc, startup=False)),
            "decode_ms": sum(t for _, t in dec), "decode_task_max_ms": max(tasks(dec, startup=True)),
            "decode_tasks": len(tasks(dec, startup=True)), "first_take_ms": take,
            "largest_part_ms": max(t for _, t in enc + dec),
        }  # fmt: skip
        for k, v in row.items():
            worst[k] = max(worst.get(k, 0.0), v)
    print({k: round(v, 1) for k, v in worst.items()}, flush=True)


if __name__ == "__main__":
    main()
