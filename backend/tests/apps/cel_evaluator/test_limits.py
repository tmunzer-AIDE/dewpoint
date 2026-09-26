# SPDX-License-Identifier: Apache-2.0
"""Real child limits and the hostile-input gate's activity-class half (spec §5.9 gate 2), against the real evaluator
process: a small zygote, like production (a child forked from pytest itself would inherit pytest's address space,
which may already exceed RLIMIT_AS). Linux only: the evaluator refuses to start elsewhere."""

import asyncio
import os
import shutil
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from dewpoint.apps import cel_client
from dewpoint.engine.cel import evaluate as E
from dewpoint.engine.cel import ipc
from dewpoint.engine.cel import types as T

P = "cel-cpp-0.1.3/fn-1/cls-1"
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="rlimits and the evaluator are Linux only")
S = "a" * 100_000 + "!"
PROBES: dict[str, tuple[str, dict[str, str], dict[str, Any], set[str]]] = {
    # name: (expression, declarations, values, acceptable outcome codes; "ok" for a value)
    "cpu_triple_all_300": ("l.all(a, l.all(b, l.all(c, a + b + c >= 0)))", {"l": T.LIST}, {"l": list(range(300))},
                           {E.ITERATION_BUDGET}),
    # Each inner map keeps ~90 MiB of accumulator copies (spec §5.5), so 256 MiB can run out before 10,000 iterations.
    "mem_nested_map_2000": ("l.map(a, l.map(b, b)).size()", {"l": T.LIST}, {"l": list(range(2000))},
                            {E.ITERATION_BUDGET, E.MEMORY_LIMIT}),
    "mem_concat_copies": ("l.map(a, s + s).size()", {"l": T.LIST, "s": T.STRING},
                          {"l": list(range(3000)), "s": S}, {E.MEMORY_LIMIT}),
    "regex_backtracking": ("s.matches('(a+)+$')", {"s": T.STRING}, {"s": S}, {"ok"}),
    "legit_out_of_subset": ("l.map(a, s + s).size()", {"l": T.LIST, "s": T.STRING},
                            {"l": list(range(20)), "s": "ab"}, {"ok"}),
}  # fmt: skip


@pytest.fixture
async def evaluator(tmp_path: Path) -> AsyncIterator[str]:
    """The real service, sized by a fake cgroup (2 GiB, no CPU quota), on a short socket path."""
    (tmp_path / "memory.max").write_text(str(2 * 1024**3))
    (tmp_path / "cpu.max").write_text("max 100000")
    sockets = tempfile.mkdtemp(dir="/tmp")
    path = os.path.join(sockets, "cel.sock")
    env = {"PATH": os.environ["PATH"], "DEWPOINT_CEL_SOCKET": path, "DEWPOINT_CEL_CGROUP": str(tmp_path)}
    if "PYTHONPATH" in os.environ:
        env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "dewpoint.apps.cel_evaluator", env=env, stderr=asyncio.subprocess.PIPE
    )
    try:
        for _ in range(100):
            try:
                if await cel_client.identity(path) == P:
                    break
            except cel_client.EvaluatorUnavailable:
                await asyncio.sleep(0.1)
        else:
            raise AssertionError("the evaluator didn't answer within 10 s")
        yield path
    finally:
        if proc.returncode is None:
            proc.terminate()
        _, stderr = await asyncio.wait_for(proc.communicate(), 10)
        shutil.rmtree(sockets, ignore_errors=True)
        assert b"refusing" not in stderr, stderr


@pytest.mark.parametrize("name", sorted(PROBES))
async def test_activity_class_probes_are_contained(evaluator: str, name: str) -> None:
    expr, decls, values, accepted = PROBES[name]
    request = ipc.EvaluateRequest(P, expr, decls, (values,))
    [outcome] = await cel_client.evaluate_remote(evaluator, request, served_profile=P)
    assert ("ok" if outcome.ok else outcome.error) in accepted, outcome
    assert await cel_client.identity(evaluator) == P  # the zygote survived


async def test_cpu_and_wall_limits_stop_a_long_evaluation(evaluator: str) -> None:
    big = "ab" * 1_000_000  # 2 MB scanned up to 9,999 times: minutes of regex work without the limits
    request = ipc.EvaluateRequest(P, "l.all(i, s.matches('^(a|b)*c$') == false)", {"l": T.LIST, "s": T.STRING},
                                  ({"l": list(range(9_999)), "s": big},))  # fmt: skip
    [outcome] = await cel_client.evaluate_remote(evaluator, request, served_profile=P)
    assert outcome.error in (E.CPU_LIMIT, E.TIMEOUT), outcome


def test_the_child_limits_are_the_documented_ones() -> None:
    import resource

    from dewpoint.apps.cel_evaluator import child

    pid = os.fork()
    if pid == 0:  # the child must never return into pytest, whatever happens
        try:
            child.apply_limits()
            got = [resource.getrlimit(r) for r in (resource.RLIMIT_AS, resource.RLIMIT_CPU, resource.RLIMIT_NOFILE,
                                                   resource.RLIMIT_FSIZE, resource.RLIMIT_CORE)]  # fmt: skip
            want = [(256 * 1024 * 1024,) * 2, (5, 6), (16, 16), (0, 0), (0, 0)]
            os._exit(0 if got == want else 1)
        finally:
            os._exit(2)
    _, status = os.waitpid(pid, 0)
    assert os.WEXITSTATUS(status) == 0
