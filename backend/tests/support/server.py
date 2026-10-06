# SPDX-License-Identifier: Apache-2.0
"""A uvicorn server in the test's own process and event loop, on a socket the test bound. It configures logging,
loads the app (calling a factory) and runs the app's lifespan in the order its command line does."""

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import uvicorn

WAIT_S = 10


def _bound() -> socket.socket:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    return sock


async def _serve(server: uvicorn.Server, sock: socket.socket) -> None:
    try:
        await server.serve(sockets=[sock])
    except SystemExit as e:  # a failed startup: escaping a task, it would stop the test's event loop
        raise AssertionError(f"the server didn't start (exit {e.code})") from None


@asynccontextmanager
async def serving(config: uvicorn.Config) -> AsyncIterator[str]:
    """The server's URL while it serves. It shuts down when the block ends, the app's lifespan shutdown included."""
    with _bound() as sock:
        server = uvicorn.Server(config)
        task = asyncio.create_task(_serve(server, sock))
        async with asyncio.timeout(WAIT_S):
            while not server.started:
                if task.done():
                    task.result()
                    raise AssertionError("the server stopped before it started")
                await asyncio.sleep(0.01)
        try:
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            async with asyncio.timeout(WAIT_S):
                await task


async def failed_start(config: uvicorn.Config) -> object:
    """The exit code uvicorn stops with when the app's lifespan startup fails."""
    with _bound() as sock, pytest.raises(SystemExit) as stopped:
        async with asyncio.timeout(WAIT_S):
            await uvicorn.Server(config).serve(sockets=[sock])
    return stopped.value.code
