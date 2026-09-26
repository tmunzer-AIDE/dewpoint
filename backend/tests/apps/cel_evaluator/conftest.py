# SPDX-License-Identifier: Apache-2.0
"""The evaluator holds no database: its tests override the root conftest's autouse cleanup. It forks per request, as
a single-threaded zygote; in-process, its tests must fork from a single-threaded pytest too."""

import asyncio
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.fixture(autouse=True)
def clean_db() -> None:
    return None


def _threads() -> list[str]:
    """This process's threads: the OS's view on Linux, where C libraries' threads count too; Python's elsewhere."""
    if sys.platform == "linux":
        return [open(f"/proc/self/task/{t}/comm").read().strip() for t in os.listdir("/proc/self/task")]
    return [t.name for t in threading.enumerate()]


@pytest.fixture(autouse=True)
async def single_threaded() -> None:
    """Forking a multi-threaded process risks a deadlocked child (and CPython only warns). The session's event loop
    keeps its default executor's threads from earlier tests: join them, and leave a fresh executor, which starts its
    threads only when used. asyncio offers no getter for the old one. On macOS a native thread from earlier tests
    can remain, which Python can't see or join (CPython still warns there); the evaluator runs on Linux only."""
    loop = asyncio.get_running_loop()
    old = getattr(loop, "_default_executor", None)
    loop.set_default_executor(ThreadPoolExecutor(thread_name_prefix="asyncio"))
    if old is not None:
        old.shutdown(wait=True)
    assert len(_threads()) == 1, _threads()
