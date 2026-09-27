# SPDX-License-Identifier: Apache-2.0
"""Concurrency from the container's own cgroup v2 limits (spec §5.7).

Each slot is charged the child's address-space limit plus its IPC buffers; a fixed reserve covers the zygote and
the server. RLIMIT_AS caps a child's virtual memory, which is never below its resident memory, so N children plus
the reserve can't exceed the cgroup's memory limit."""

import math
from dataclasses import dataclass
from pathlib import Path

from dewpoint.apps.cel_evaluator.config import StartupError

MIB = 1024 * 1024
CHILD_MEMORY = 256 * MIB  # RLIMIT_AS of each child
SLOT_BUFFERS = 8 * MIB + MIB // 4  # one in-flight request (4 MiB), one queued request (4 MiB), one response
RESERVE = 256 * MIB  # the zygote and the IPC server
PIDS_OVERHEAD = 8  # the zygote and its helpers; each slot needs one more pid


@dataclass(frozen=True)
class Capacity:
    slots: int
    memory_limit: int
    cpus: float
    pids_limit: int | None


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        return None


def derive(cgroup: Path, cpu_count: int, configured: int | None) -> Capacity:
    memory = _read(cgroup / "memory.max")
    if memory is None or memory == "max":
        raise StartupError(
            "refusing to start without a cgroup memory limit: set one (Compose `mem_limit`; 2 GiB gives up to 6 slots)"
        )
    memory_limit = int(memory)
    cpu = _read(cgroup / "cpu.max")
    if cpu is None or cpu.startswith("max"):
        cpus = float(cpu_count)
    else:
        quota, period = cpu.split()
        cpus = int(quota) / int(period)
    pids = _read(cgroup / "pids.max")
    pids_limit = None if pids is None or pids == "max" else int(pids)
    slots = min(math.floor(cpus), (memory_limit - RESERVE) // (CHILD_MEMORY + SLOT_BUFFERS))
    if pids_limit is not None:
        slots = min(slots, pids_limit - PIDS_OVERHEAD)
    if configured is not None:
        slots = min(slots, configured)  # configuration may lower N, never raise it
    if slots < 1:
        raise StartupError(
            f"refusing to start: the limits allow {slots} evaluation slots (memory {memory_limit // MIB} MiB, "
            f"{cpus:g} CPUs, pids {pids_limit}). Each slot needs 264.25 MiB and one CPU, plus a 256 MiB reserve."
        )
    return Capacity(slots, memory_limit, cpus, pids_limit)
