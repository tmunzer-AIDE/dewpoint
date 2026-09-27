# SPDX-License-Identifier: Apache-2.0
"""The evaluator's server and child, on any POSIX system. Child limits are replaced by test hooks here; the real
rlimits are exercised on Linux in test_limits.py."""

import asyncio
import os
import signal
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

from dewpoint.apps import cel_client
from dewpoint.apps.cel_evaluator import server
from dewpoint.engine.cel import evaluate as E
from dewpoint.engine.cel import ipc
from dewpoint.engine.cel import types as T

P = "cel-cpp-0.1.3/fn-1/cls-1"
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")


def request(expr: str = "x + 1", *bindings: dict[str, Any], profile: str = P) -> ipc.EvaluateRequest:
    return ipc.EvaluateRequest(profile, expr, {"x": T.DYN}, bindings or ({"x": 1},))


async def _serve(evaluator: server.Evaluator) -> AsyncIterator[str]:
    with tempfile.TemporaryDirectory(dir="/tmp") as d:  # AF_UNIX paths are limited to ~100 bytes
        path = os.path.join(d, "cel.sock")
        srv = await asyncio.start_unix_server(evaluator.handle, path=path)
        async with srv:
            yield path


def evaluator_with(limit: Callable[[], None] = lambda: None, **kwargs: Any) -> Callable[[], AsyncIterator[str]]:
    return lambda: _serve(server.Evaluator(P, kwargs.pop("slots", 2), limit=limit, **kwargs))


async def _one(ev: Callable[[], AsyncIterator[str]]) -> tuple[AsyncIterator[str], str]:
    gen = ev()
    return gen, await gen.__anext__()


async def test_identity_and_evaluation() -> None:
    gen, path = await _one(evaluator_with())
    assert await cel_client.identity(path) == P
    got = await cel_client.evaluate_remote(path, request("x + 1", {"x": 1}, {"x": "a"}), served_profile=P)
    assert got[0] == E.Outcome(value=2) and got[1].error == E.EVALUATION_ERROR
    await gen.aclose()


async def test_profiles_fail_closed() -> None:
    gen, path = await _one(evaluator_with())
    other = request(profile="cel-cpp-9.9.9/fn-1/cls-1")
    assert (await cel_client.evaluate_remote(path, other, served_profile="cel-cpp-9.9.9/fn-1/cls-1"))[0].error == (
        E.PROFILE_UNAVAILABLE
    )
    assert (await cel_client.evaluate_remote(path, other, served_profile=P))[0].error == E.PROFILE_UNAVAILABLE
    await gen.aclose()


async def test_malformed_and_oversized_frames_close_the_connection() -> None:
    gen, path = await _one(evaluator_with())
    for frame in (b"\x00\x00\x00\x03abc", (ipc.MAX_REQUEST + 1).to_bytes(4, "big")):
        reader, writer = await asyncio.open_unix_connection(path)
        writer.write(frame)
        await writer.drain()
        assert await reader.read() == b""  # closed without a reply
        writer.close()
    await gen.aclose()


async def test_a_hung_child_is_killed_at_the_wall_clock_limit() -> None:
    gen, path = await _one(evaluator_with(lambda: time.sleep(30), wall=0.5))
    started = time.monotonic()
    got = await cel_client.evaluate_remote(path, request(), served_profile=P)
    assert got[0].error == E.TIMEOUT and time.monotonic() - started < 5
    await gen.aclose()


@pytest.mark.parametrize(
    ("sig", "code"), [(signal.SIGXCPU, E.CPU_LIMIT), (signal.SIGSEGV, E.CRASHED), (signal.SIGABRT, E.CRASHED)]
)
async def test_how_a_child_died_decides_the_outcome(sig: int, code: str) -> None:
    gen, path = await _one(evaluator_with(lambda: os.kill(os.getpid(), sig)))
    assert (await cel_client.evaluate_remote(path, request(), served_profile=P))[0].error == code
    assert await cel_client.identity(path) == P  # the zygote survived
    await gen.aclose()


async def test_memory_errors_are_an_outcome() -> None:
    def exhausted() -> None:
        raise MemoryError

    gen, path = await _one(evaluator_with(exhausted))
    assert (await cel_client.evaluate_remote(path, request(), served_profile=P))[0].error == E.MEMORY_LIMIT
    await gen.aclose()


async def test_busy_above_n_running_plus_n_waiting() -> None:
    gen, path = await _one(evaluator_with(lambda: time.sleep(1.0), slots=1))
    calls = [cel_client.evaluate_remote(path, request(), served_profile=P) for _ in range(3)]
    results = await asyncio.gather(*calls, return_exceptions=True)
    busy = [r for r in results if isinstance(r, cel_client.EvaluatorUnavailable)]
    assert len(busy) == 1 and sum(1 for r in results if isinstance(r, list) and r[0].ok) == 2
    await gen.aclose()


async def test_an_unreachable_evaluator_is_an_infrastructure_error(tmp_path: Path) -> None:
    with pytest.raises(cel_client.EvaluatorUnavailable):
        await cel_client.identity(str(tmp_path / "nowhere.sock"))


async def test_oversized_requests_are_an_outcome_before_sending(tmp_path: Path) -> None:
    big = request("x", {"x": "y" * (ipc.MAX_REQUEST + 1)})
    got = await cel_client.evaluate_remote(str(tmp_path / "nowhere.sock"), big, served_profile=P)
    assert got[0].error == E.INPUT_TOO_LARGE


async def _replying(reply: Any) -> AsyncIterator[str]:
    """A fake evaluator answering every request with `reply`, framed."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await ipc.read_frame(reader, ipc.MAX_REQUEST)
        writer.write(ipc.encode(reply))
        await writer.drain()
        writer.close()

    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        path = os.path.join(d, "cel.sock")
        async with await asyncio.start_unix_server(handle, path=path):
            yield path


TWO = request("x + 1", {"x": 1}, {"x": "a"})  # two binding sets


@pytest.mark.parametrize(
    "reply",
    [
        {"schema": ipc.SCHEMA},  # neither results nor an error: was recorded as the error "None"
        {"schema": ipc.SCHEMA, "results": [{"ok": 2}]},  # one result for two binding sets
        {"schema": ipc.SCHEMA, "results": [{"ok": 2}, {"ok": 3}, {"ok": 4}]},
        {"schema": ipc.SCHEMA, "results": "x"},
        {"schema": ipc.SCHEMA, "results": [{"ok": 2}, {"nope": 1}]},
        {"schema": ipc.SCHEMA, "results": [{"ok": 2}, {"ok": 3, "error": "timeout"}]},
        {"schema": ipc.SCHEMA, "results": [{"ok": 2}, {"error": "made_up"}]},
        {"schema": ipc.SCHEMA, "results": [{"ok": 2}, {"error": ["timeout"]}]},
        {"schema": ipc.SCHEMA, "error": 5},
        {"schema": ipc.SCHEMA, "error": "made_up"},
        {"schema": ipc.SCHEMA, "error": "timeout", "message": 5},
        {"schema": "other.v9", "results": [{"ok": 2}, {"ok": 3}]},
        {"schema": ipc.SCHEMA, "results": [{"ok": 2}, {"ok": 3}], "extra": 1},
    ],
)
async def test_a_reply_that_breaks_the_protocol_is_an_infrastructure_error(reply: Any) -> None:
    """Review finding: a malformed reply must be retried, never recorded as the step's outcome."""
    gen, path = await _one(lambda: _replying(reply))
    try:
        with pytest.raises(cel_client.EvaluatorUnavailable):
            await cel_client.evaluate_remote(path, TWO, served_profile=P)
    finally:
        await gen.aclose()


@pytest.mark.parametrize(
    ("reply", "outcomes"),
    [
        (
            {"schema": ipc.SCHEMA, "results": [{"ok": 2}, {"error": E.TYPE_MISMATCH, "message": "m"}]},
            [E.Outcome(value=2), E.Outcome(error=E.TYPE_MISMATCH, message="m")],
        ),
        ({"schema": ipc.SCHEMA, "error": E.TIMEOUT, "message": "t"}, [E.Outcome(error=E.TIMEOUT, message="t")] * 2),
        ({"schema": ipc.SCHEMA, "error": "rejected"}, [E.Outcome(error="rejected")] * 2),
    ],
)
async def test_a_well_formed_reply_is_recorded(reply: Any, outcomes: list[E.Outcome]) -> None:
    gen, path = await _one(lambda: _replying(reply))
    try:
        assert await cel_client.evaluate_remote(path, TWO, served_profile=P) == outcomes
    finally:
        await gen.aclose()
