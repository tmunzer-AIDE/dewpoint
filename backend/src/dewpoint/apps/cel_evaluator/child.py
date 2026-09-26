# SPDX-License-Identifier: Apache-2.0
"""One evaluation in a forked child (spec §5.7): limits first, then the request, then exit. The child never returns
into the zygote's event loop: it writes one frame to its pipe and calls os._exit."""

import os
import resource
from collections.abc import Callable
from typing import NoReturn

from dewpoint.apps.cel_evaluator.capacity import CHILD_MEMORY
from dewpoint.engine.cel import evaluate, ipc

CPU_SECONDS = 5
OPEN_FILES = 16


def apply_limits() -> None:
    """Linux: RLIMIT_AS 256 MiB, RLIMIT_CPU 5 s (hard 6 s), 16 descriptors, no file writes, no core dumps."""
    resource.setrlimit(resource.RLIMIT_AS, (CHILD_MEMORY, CHILD_MEMORY))
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_NOFILE, (OPEN_FILES, OPEN_FILES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _isolate(keep: int) -> None:
    """Standard streams to /dev/null, every other descriptor closed except the result pipe."""
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    os.closerange(3, keep)
    os.closerange(keep + 1, os.sysconf("SC_OPEN_MAX"))


def run(request: ipc.EvaluateRequest, write_fd: int, limit: Callable[[], None]) -> NoReturn:
    try:
        _isolate(write_fd)
        limit()
        response = ipc.evaluate_request(request)
    except MemoryError:
        response = ipc.error_response(evaluate.MEMORY_LIMIT, "the evaluation ran out of its 256 MiB")
    except BaseException as e:  # noqa: BLE001  # whatever happens, the zygote gets one frame and the child exits
        response = ipc.error_response(evaluate.CRASHED, type(e).__name__)
    try:
        frame = memoryview(ipc.encode(response))
        while frame:
            frame = frame[os.write(write_fd, frame) :]
    finally:
        os._exit(0)
