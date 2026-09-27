# SPDX-License-Identifier: Apache-2.0
"""The zygote's IPC server (spec §5.7): single-threaded asyncio on a Unix socket, one request per connection.

At most N children run at once, with a wait queue of N; anything beyond gets `busy`, and so does a request the OS
can't start a child for (no process, memory or descriptor to spare). A child that isn't done after
5 s of wall-clock time is killed (`timeout`). How a child ended decides the outcome: its own frame, `cpu_limit`
(SIGXCPU, or SIGKILL at the hard CPU limit), or `evaluation_crashed`."""

import asyncio
import contextlib
import json
import os
import signal
import struct
from collections.abc import Callable
from typing import Any

from dewpoint.apps.cel_evaluator import child
from dewpoint.engine.cel import evaluate, ipc

WALL_SECONDS = 5.0
READ_SECONDS = 10.0  # a client that doesn't send its frame in time is dropped
_HEADER = struct.Struct(">I")


class Evaluator:
    def __init__(
        self, profile: str, slots: int, *, limit: Callable[[], None] = child.apply_limits, wall: float = WALL_SECONDS
    ) -> None:
        self.profile, self.slots, self.limit, self.wall = profile, slots, limit, wall
        self._running = asyncio.Semaphore(slots)
        self._waiting = 0

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                message = await asyncio.wait_for(ipc.read_frame(reader, ipc.MAX_REQUEST), READ_SECONDS)
                request = ipc.parse_request(message)
            except (ipc.FrameError, asyncio.IncompleteReadError, TimeoutError):
                return  # malformed, oversized or silent: close without a reply
            if isinstance(request, ipc.IdentityRequest):
                response = ipc.identity_response(self.profile)
            elif request.profile != self.profile:
                response = ipc.error_response("profile_mismatch", f"this evaluator serves {self.profile}")
            else:
                response = await self.evaluate(request)
            writer.write(ipc.encode(response))
            await writer.drain()
        finally:
            writer.close()

    async def evaluate(self, request: ipc.EvaluateRequest) -> dict[str, Any]:
        if self._running.locked() and self._waiting >= self.slots:
            return ipc.error_response("busy")
        self._waiting += 1
        try:
            await self._running.acquire()
        finally:
            self._waiting -= 1
        try:
            return await self._fork(request)
        finally:
            self._running.release()

    async def _fork(self, request: ipc.EvaluateRequest) -> dict[str, Any]:
        try:
            read_fd, write_fd = os.pipe()
        except OSError as e:
            return ipc.error_response("busy", f"no descriptor for an evaluation: {e.strerror}")
        try:
            pid = os.fork()
        except OSError as e:  # out of processes or memory: the client retries, as for any busy answer
            os.close(read_fd)
            os.close(write_fd)
            return ipc.error_response("busy", f"couldn't start an evaluation: {e.strerror}")
        if pid == 0:  # the child: never returns
            os.close(read_fd)
            child.run(request, write_fd, self.limit)
        os.close(write_fd)
        os.set_blocking(read_fd, False)
        loop = asyncio.get_running_loop()
        received = bytearray()
        finished: asyncio.Future[None] = loop.create_future()

        def readable() -> None:
            try:
                chunk = os.read(read_fd, 65_536)
            except BlockingIOError:
                return
            received.extend(chunk)
            if (not chunk or len(received) > _HEADER.size + ipc.MAX_RESPONSE) and not finished.done():
                finished.set_result(None)

        loop.add_reader(read_fd, readable)
        timed_out = False
        try:
            await asyncio.wait_for(finished, self.wall)
        except TimeoutError:
            timed_out = True
        finally:
            loop.remove_reader(read_fd)
            os.close(read_fd)
        if timed_out or len(received) > _HEADER.size + ipc.MAX_RESPONSE:
            os.kill(pid, signal.SIGKILL)
        status = await _reap(pid)
        if timed_out:
            return ipc.error_response(evaluate.TIMEOUT, f"no result after {self.wall:g} s")
        return _outcome(status, bytes(received))


async def _reap(pid: int) -> int:
    """The child has closed its pipe or been killed; collect it without blocking the loop."""
    while True:
        done, status = os.waitpid(pid, os.WNOHANG)  # noqa: ASYNC222  # WNOHANG never blocks
        if done:
            return status
        await asyncio.sleep(0.001)


def _outcome(status: int, received: bytes) -> dict[str, Any]:
    if os.WIFSIGNALED(status):
        sig = os.WTERMSIG(status)
        if sig in (signal.SIGXCPU, signal.SIGKILL):
            return ipc.error_response(evaluate.CPU_LIMIT, f"more than {child.CPU_SECONDS} s of CPU")
        return ipc.error_response(evaluate.CRASHED, f"the evaluation ended with signal {signal.Signals(sig).name}")
    if len(received) >= _HEADER.size:
        (length,) = _HEADER.unpack_from(received)
        if length == len(received) - _HEADER.size <= ipc.MAX_RESPONSE:
            message = json.loads(received[_HEADER.size :])
            if isinstance(message, dict):
                return message
    return ipc.error_response(evaluate.CRASHED, "the evaluation ended without a result")


async def serve(socket_path: str, evaluator: Evaluator, *, ready: Callable[[], None] | None = None) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(socket_path)  # a stale socket from a previous run
    server = await asyncio.start_unix_server(evaluator.handle, path=socket_path)
    # The socket lives on a volume mounted only by this service and the CEL activity worker, which runs as another
    # user: the volume is the access boundary, so the socket itself is open to both.
    os.chmod(socket_path, 0o666)  # noqa: S103
    loop = asyncio.get_running_loop()
    stop: asyncio.Future[None] = loop.create_future()

    def request_stop() -> None:
        if not stop.done():
            stop.set_result(None)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, request_stop)
    if ready is not None:
        ready()
    async with server:
        await stop
