# SPDX-License-Identifier: Apache-2.0
"""How a long-running process stops (`dewpoint worker`, `dispatcher`, `retention`). SIGTERM or SIGINT asks it to
(Compose's stop, a recreate on deploy, Ctrl-C): it stops at its own safe points, taking no new work and ending the work
in hand within its grace, and exits 0. A second signal ends it at once, 128 + its number, as a supervisor's SIGKILL
would. It handles the signals itself, so it stops as PID 1 too, where the kernel drops a signal without a handler.

It leaves through `leave`: its logs and stdio flushed, then `os._exit`, without interpreter finalization. Finalization
can crash in temporalio's bridge (1.33.0): a bridge future that completes on a tokio thread while the interpreter
finalizes drops Python objects without a thread state (SIGSEGV or SIGABRT, the replay subprocess's crash in #108).
So no atexit handler runs: Dewpoint registers none, the logs are flushed here, and a thread still running (an SMTP
send past the grace) is cut, as SIGKILL cuts it."""

import asyncio
import logging
import os
import signal
import sys
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from typing import Any, NoReturn

import structlog

log = structlog.get_logger("dewpoint.stopping")
SIGNALS = (signal.SIGTERM, signal.SIGINT)
_exit: Callable[[int], NoReturn] = os._exit  # the suite's raises SystemExit instead (tests/conftest.py)


@contextmanager
def stop_signals(requested: asyncio.Event) -> Iterator[None]:
    """While it's open, in the running loop: the first SIGTERM or SIGINT sets `requested`, and the next one leaves at
    once (`leave`, 143 or 130). The handlers before it are back afterwards."""
    loop = asyncio.get_running_loop()

    def received(sig: signal.Signals) -> None:
        if requested.is_set():
            log.warning("stop_forced", signal=sig.name)
            leave(128 + sig)
        else:
            log.info("stop_requested", signal=sig.name)
            requested.set()

    before = {sig: signal.getsignal(sig) for sig in SIGNALS}
    try:
        for sig in SIGNALS:
            loop.add_signal_handler(sig, received, sig)
        yield
    finally:
        for sig, handler in before.items():
            loop.remove_signal_handler(sig)
            if handler is not None:  # None: one not installed from Python, which can't be put back from it
                signal.signal(sig, handler)


async def stoppable[T](run: Callable[[asyncio.Event], Awaitable[T]]) -> T:
    """`run(requested)`, `requested` set by the first SIGTERM or SIGINT (`stop_signals`)."""
    requested = asyncio.Event()
    with stop_signals(requested):
        return await run(requested)


async def pause(requested: asyncio.Event, seconds: float) -> None:
    """`seconds`, or until a stop is requested."""
    with suppress(TimeoutError):
        await asyncio.wait_for(requested.wait(), seconds)


async def unless_stopped[T](requested: asyncio.Event, work: Awaitable[T]) -> T | None:
    """`work`'s result (or its exception); None once a stop is requested first, `work` cancelled and awaited. A process
    still starting has taken nothing: it stops at once."""
    task = asyncio.ensure_future(work)
    asked = asyncio.ensure_future(requested.wait())
    try:
        await asyncio.wait((task, asked), return_when=asyncio.FIRST_COMPLETED)
    finally:
        asked.cancel()
        task.cancel()  # nothing, once it's done
        await asyncio.gather(task, asked, return_exceptions=True)
    return None if task.cancelled() else task.result()


async def serve(serving: Iterable[Awaitable[None]], helpers: Iterable[Awaitable[None]], *,
                halt: Callable[[], Awaitable[None]], requested: asyncio.Event) -> None:  # fmt: skip
    """`serving`, work that ends once `halt` has run, beside `helpers`, work that may never end, until every serving
    task has ended. `halt` runs once a stop is requested or once any of them raises; once the serving work has ended,
    the helpers are cancelled and awaited, and so is the halt if it still waits (temporalio's `Worker.shutdown()` never
    returns for a worker whose `run()` failed before it polled), and the first exception is raised. So a process stops
    taking work before it goes, whatever ends it, and leaves nothing of its own running. A helper that fails stops the
    serving work by raising: it should not halt it itself, since one that raises only once it has (the SDK's
    `shutdown()` returns once `run()` has ended) would be cancelled with the helpers first."""
    work = [asyncio.ensure_future(w) for w in serving]
    helping = [asyncio.ensure_future(h) for h in helpers]
    asked = asyncio.ensure_future(requested.wait())
    halting: asyncio.Future[None] | None = None
    failure: BaseException | None = None
    try:
        pending: set[asyncio.Future[Any]] = {*work, *helping, asked}
        while not all(w.done() for w in work):
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if failure is None and task is not asked and not task.cancelled():
                    failure = task.exception()
            if halting is None and (asked.done() or failure is not None):
                halting = asyncio.ensure_future(halt())
                pending.add(halting)
    finally:
        everything: list[asyncio.Future[Any]] = [*work, *helping, asked, *([halting] if halting is not None else [])]
        for task in everything:
            task.cancel()  # nothing, once it's done: the helpers and a halt still waiting, or all if this was cancelled
        await asyncio.gather(*everything, return_exceptions=True)
    if failure is not None:
        raise failure


def leave(code: int) -> NoReturn:
    """Ends the process with `code`, its logs and stdio flushed first, skipping interpreter finalization (above). Only
    once its work has stopped: whatever still runs is cut."""
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    _exit(code)
