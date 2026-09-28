# SPDX-License-Identifier: Apache-2.0
"""Gate 4 (spec §5.9): Temporal replay. A sandboxed workflow evaluates the gate corpus in-process; its history is
recorded once, then replayed in 5 fresh processes with different PYTHONHASHSEED values. The C++ runtime seeds its
maps per process, so this catches iteration order leaking into what a workflow computes. The corpus holds only what
publish accepts: gate 1's cases that compile and iterate only proven lists, and maps read through sortedKeys."""

import asyncio
import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path
from typing import Any

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.engine.cel import classify, runtime
from dewpoint.engine.cel import types as T
from tests.engine.cel.gate_replay_workflow import CelCorpus, outcomes
from tests.engine.cel.test_gate_semantics import CASES

BACKEND = Path(__file__).parents[3]
REPLAY = textwrap.dedent(
    """
    import asyncio, sys
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer
    from tests.engine.cel.gate_replay_workflow import CelCorpus

    history = WorkflowHistory.from_json("gate4", open(sys.argv[1]).read())
    asyncio.run(Replayer(workflows=[CelCorpus]).replay_workflow(history))
    """
)
M = {f"k{i:02d}": i for i in reversed(range(24))}  # built in reverse: the runtime's order is its own
MAPS: list[list[Any]] = [
    ["sortedKeys(m)", {"m": T.MAP}, {"m": M}],
    ["sortedKeys(m).map(k, m[k] * 2)", {"m": T.MAP}, {"m": M}],
    ["m", {"m": T.MAP}, {"m": M}],
    ["{'b': m.k01, 'a': m.k02, 'c': [m.k03, {'z': 1, 'y': 2}]}", {"m": T.MAP}, {"m": M}],
    ["sortedKeys(m).exists_one(k, 10 / m[k] > 3)", {"m": T.MAP}, {"m": M}],
    ["'k03' in m && m == m", {"m": T.MAP}, {"m": M}],
    ["[macNormalize('5C:5B:35:00:00:01'), ipInCidr('10.1.2.3', '10.0.0.0/8')]", {}, {}],
]
LEAK = ["m.map(k, k)", {"m": T.MAP}, {"m": M}]  # iterates a map: publish refuses it


def publishable(expr: str, decls: dict[str, str]) -> bool:
    try:
        return not classify.order_problems(runtime.compile_checked(expr, decls).checked)
    except runtime.CompileError:
        return False


def corpus() -> list[list[Any]]:
    cases = [[e, {n: T.DYN for n in v}, v] for e, v, _ in CASES]
    return [c for c in cases if publishable(c[0], c[1])] + MAPS


async def recorded(path: Path, items: list[list[Any]]) -> Path:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(env.client, task_queue="gate4", workflows=[CelCorpus], activities=[outcomes]):
            handle = await env.client.start_workflow(CelCorpus.run, items, id=str(uuid.uuid4()), task_queue="gate4")
            await asyncio.wait_for(handle.result(), 120)
            history = (await handle.fetch_history()).to_json()
    await asyncio.to_thread(path.write_text, history)
    return path


def replays(history: Path) -> list[str]:
    """What each replay reported on stderr, in 5 fresh processes with different hash seeds: "" when it passed."""
    out = []
    for seed in range(5):
        done = subprocess.run(
            [sys.executable, "-c", REPLAY, str(history)],
            cwd=BACKEND,
            env={**os.environ, "PYTHONHASHSEED": str(seed * 7919 + 1)},
            capture_output=True,
            text=True,
            timeout=120,
        )
        out.append("" if done.returncode == 0 else done.stderr or f"exit {done.returncode}")
    return out


def test_the_corpus_is_what_publish_accepts() -> None:
    items = corpus()
    assert len(items) == 71 + len(MAPS)  # gate 1's 82 cases, less 6 that don't compile and 5 over unproven lists
    assert all(publishable(e, d) for e, d, _ in items) and not publishable(LEAK[0], LEAK[1])


async def test_the_corpus_replays_identically_in_five_fresh_processes(tmp_path: Path) -> None:
    assert replays(await recorded(tmp_path / "gate4.json", corpus())) == [""] * 5


async def test_the_gate_catches_iteration_order_leaking(tmp_path: Path) -> None:
    """The bite check: a comprehension over a map, which publish refuses, computes a different list in another
    process, and its replay fails."""
    failed = [r for r in replays(await recorded(tmp_path / "leak.json", [*corpus(), LEAK])) if r]
    assert failed and all("[TMPRL1100] Nondeterminism error: Activity id" in r for r in failed)
