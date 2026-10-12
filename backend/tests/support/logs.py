# SPDX-License-Identifier: Apache-2.0
"""What structlog writes, as text: each line as the configured processors render it. And the standard library's
logging, put back as it was after a test that configures the process or runs uvicorn."""

import json
import logging
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import structlog

UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")  # the loggers uvicorn configures
HTTP = ("httpx", "httpcore")  # the HTTP libraries' loggers, whose levels configuring the process sets


@contextmanager
def rendered() -> Iterator[Callable[[], list[str]]]:
    """The lines structlog renders from here on: with its defaults until the code under test configures it. Only the
    output's destination is replaced (a configuration that names none keeps it); the defaults are back afterwards."""
    structlog.reset_defaults()
    factory = structlog.testing.CapturingLoggerFactory()
    structlog.configure(logger_factory=factory)
    try:
        yield lambda: [str(call.args[0]) for call in factory.logger.calls]
    finally:
        structlog.reset_defaults()


@contextmanager
def stdlib_restored() -> Iterator[None]:
    """The root logger's handlers and level, and uvicorn's and the HTTP libraries' loggers, as they were afterwards:
    configuring the process and uvicorn's own configuration both change them."""
    root = logging.getLogger()
    handlers, root_level = root.handlers[:], root.level
    loggers = {name: logging.getLogger(name) for name in (*UVICORN, *HTTP)}
    saved = {name: (lg.handlers[:], lg.propagate, lg.level, lg.disabled) for name, lg in loggers.items()}
    try:
        yield
    finally:
        root.handlers[:] = handlers
        root.setLevel(root_level)
        for name, (kept, propagate, level, disabled) in saved.items():
            lg = loggers[name]
            lg.handlers[:], lg.propagate, lg.disabled = kept, propagate, disabled
            lg.setLevel(level)


def records(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Each line as the JSON object it must be."""
    return [json.loads(line) for line in lines]
