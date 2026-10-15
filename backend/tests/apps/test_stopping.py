# SPDX-License-Identifier: Apache-2.0
"""How a long-running process stops: the first SIGTERM or SIGINT asks it to, the second ends it at once; it stops
taking work, ends the work in hand, cancels what only helps it, and leaves flushed, through `os._exit`."""

import asyncio
import io
import logging
import os
import signal
import sys
from collections.abc import Callable
from types import FrameType

import pytest
from structlog.testing import capture_logs

from dewpoint.apps import stopping


async def turns(until: Callable[[], object], at_most: int = 100) -> None:
    """The loop's turns, until `until()` holds: a signal sent to this process, or a task just made, is handled within a
    few."""
    for _ in range(at_most):
        if until():
            return
        await asyncio.sleep(0)


async def test_the_first_signal_asks_to_stop_and_the_second_leaves_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose sends one SIGTERM, then SIGKILL after its grace; a second signal (Ctrl-C again) is the person's own
    SIGKILL: 128 + its number, as a shell reports it."""
    left: list[int] = []
    monkeypatch.setattr(stopping, "_exit", left.append)
    requested = asyncio.Event()
    with capture_logs() as logged, stopping.stop_signals(requested):
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(requested.wait(), 10)
        assert left == []
        os.kill(os.getpid(), signal.SIGINT)
        await turns(lambda: left)
    assert left == [130]
    assert [(e["event"], e["signal"]) for e in logged] == [("stop_requested", "SIGTERM"), ("stop_forced", "SIGINT")]


async def test_the_signals_handlers_are_put_back_afterwards() -> None:
    def mine(signum: int, frame: FrameType | None) -> None: ...

    before, interrupt = signal.signal(signal.SIGTERM, mine), signal.getsignal(signal.SIGINT)  # asyncio's Runner's
    try:
        with stopping.stop_signals(asyncio.Event()):
            assert signal.getsignal(signal.SIGTERM) is not mine
        assert signal.getsignal(signal.SIGTERM) is mine
        assert signal.getsignal(signal.SIGINT) is interrupt
    finally:
        signal.signal(signal.SIGTERM, before)


async def test_a_pause_ends_once_a_stop_is_requested() -> None:
    requested = asyncio.Event()
    pausing = asyncio.ensure_future(stopping.pause(requested, 3600))
    await asyncio.sleep(0)
    assert not pausing.done()
    requested.set()
    await asyncio.wait_for(pausing, 10)  # not an hour later


async def test_unless_stopped_gives_the_works_result_or_its_failure() -> None:
    async def answer() -> str:
        return "client"

    async def failing() -> str:
        raise LookupError("no environment recorded")

    assert await stopping.unless_stopped(asyncio.Event(), answer()) == "client"
    with pytest.raises(LookupError):
        await stopping.unless_stopped(asyncio.Event(), failing())


async def test_a_stop_requested_first_cancels_the_work() -> None:
    """A worker still starting (waiting for its evaluator, say) has taken nothing: it stops at once."""
    events: list[str] = []
    requested = asyncio.Event()

    async def starting() -> str:
        try:
            requested.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            events.append("cancelled")
            raise
        return "never"

    assert await stopping.unless_stopped(requested, starting()) is None
    assert events == ["cancelled"]


class Serving:
    """A worker's shape: it serves until halted, then ends; and a helper that never ends on its own."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.halted = asyncio.Event()

    async def serve(self, name: str) -> None:
        self.events.append(f"{name} serving")
        await self.halted.wait()
        self.events.append(f"{name} ended")

    async def halt(self) -> None:
        self.events.append("halt")
        self.halted.set()

    async def helper(self, name: str) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.events.append(f"{name} cancelled")
            raise

    async def failing(self, error: Exception) -> None:
        await asyncio.sleep(0)
        raise error


async def test_a_stop_request_halts_the_serving_work_then_cancels_the_helpers() -> None:
    s, requested = Serving(), asyncio.Event()
    serving = asyncio.ensure_future(stopping.serve([s.serve("engine"), s.serve("cel")], [s.helper("watch")],
                                                   halt=s.halt, requested=requested))  # fmt: skip
    await turns(lambda: len(s.events) == 2)
    assert s.events == ["engine serving", "cel serving"]
    requested.set()
    await asyncio.wait_for(serving, 10)
    assert s.events == ["engine serving", "cel serving", "halt", "engine ended", "cel ended", "watch cancelled"]


async def test_a_helpers_failure_halts_the_serving_work_first_then_is_raised() -> None:
    """A `promote` that runs out of time: the workers stop taking work before the process goes."""
    s = Serving()
    with pytest.raises(LookupError):
        await asyncio.wait_for(stopping.serve([s.serve("engine")], [s.failing(LookupError()), s.helper("token")],
                                              halt=s.halt, requested=asyncio.Event()), 10)  # fmt: skip
    assert s.events == ["engine serving", "halt", "engine ended", "token cancelled"]


async def test_a_serving_tasks_failure_halts_the_others() -> None:
    """A worker's fatal error: the plugin-call server and the other worker stop too, rather than run on alone."""
    s = Serving()
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(stopping.serve([s.serve("cel"), s.failing(RuntimeError("fatal"))], [s.helper("watch")],
                                              halt=s.halt, requested=asyncio.Event()), 10)  # fmt: skip
    assert s.events == ["cel serving", "halt", "cel ended", "watch cancelled"]


async def test_serving_work_that_ends_on_its_own_ends_the_helpers_too() -> None:
    """No stop requested and nothing raised: what only helped the serving work goes with it."""
    s = Serving()

    async def served() -> None:
        s.events.append("served")

    await asyncio.wait_for(stopping.serve([served()], [s.helper("token")], halt=s.halt, requested=asyncio.Event()), 10)
    assert s.events == ["served", "token cancelled"]


async def test_a_halt_that_never_returns_never_holds_the_process_once_its_work_has_ended() -> None:
    """temporalio's Worker (the fresh review's finding 2): one whose `run()` failed before it polled never completes a
    `shutdown()`. Once every serving task has ended, the halt has nothing left to do: its wait is cut."""
    s = Serving()

    async def halt() -> None:
        await s.halt()
        await asyncio.Event().wait()  # the failed worker's shutdown, which never returns

    with pytest.raises(RuntimeError):
        await asyncio.wait_for(stopping.serve([s.serve("cel"), s.failing(RuntimeError("refused"))], [s.helper("watch")],
                                              halt=halt, requested=asyncio.Event()), 10)  # fmt: skip
    assert "cel ended" in s.events and s.events[-1] == "watch cancelled"


class Flushes(io.StringIO):
    def __init__(self, name: str, events: list[str]) -> None:
        super().__init__()
        self.name, self.events = name, events

    def flush(self) -> None:
        self.events.append(f"{self.name} flushed")


class Handler(logging.Handler):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def emit(self, record: logging.LogRecord) -> None: ...

    def flush(self) -> None:
        self.events.append("handler flushed")


def test_leaving_flushes_the_logs_and_stdio_then_exits_with_the_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interpreter finalization is skipped (temporalio's bridge can crash in it), and with it what would have flushed:
    the logging handlers and the streams, flushed here first."""
    events: list[str] = []
    monkeypatch.setattr(sys, "stdout", Flushes("stdout", events))
    monkeypatch.setattr(sys, "stderr", Flushes("stderr", events))
    monkeypatch.setattr(stopping, "_exit", lambda code: events.append(f"exit {code}"))
    handler = Handler(events)
    logging.getLogger().addHandler(handler)
    try:
        stopping.leave(3)
    finally:
        logging.getLogger().removeHandler(handler)
    # every handler is flushed, the process's own (to stderr) included, so the order between them isn't the point
    assert {"handler flushed", "stdout flushed", "stderr flushed"} <= set(events[:-1]) and events[-1] == "exit 3"


def test_a_test_that_leaves_ends_with_system_exit_never_the_process() -> None:
    """The suite's own guard (conftest): os._exit would end the pytest worker."""
    with pytest.raises(SystemExit) as left:
        stopping.leave(2)
    assert left.value.code == 2
