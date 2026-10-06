# SPDX-License-Identifier: Apache-2.0
"""How every process logs (the API, the worker, the dispatcher, ingress, each admin command): one JSON object per
line, and an exception by its type and the innermost frames it was raised through, never by a value. structlog's
defaults render a rich traceback with every frame's local variables (a password a route read from its body, a token,
a response's body), and an exception's text can quote whatever it was given: neither is logged.

A frame is named by its file, function and line, which are its code's. A plugin step's bug is logged by the worker's
own, stricter, rules (dewpoint.apps.worker.logs)."""

import os
import sys
import traceback

import structlog
from structlog.typing import EventDict, WrappedLogger

WHERE_FRAMES = 8  # the innermost frames an exception's log names


def _exception(exc_info: object) -> BaseException | None:
    """The exception `exc_info` names: an exception, an exc_info tuple, or any true value for the one being handled."""
    if isinstance(exc_info, BaseException):
        return exc_info
    if isinstance(exc_info, tuple) and len(exc_info) == 3 and isinstance(exc_info[1], BaseException):
        return exc_info[1]
    return sys.exception() if exc_info else None


def exception_type(logger: WrappedLogger, method: str, event_dict: EventDict) -> EventDict:
    """Replace `exc_info` (`log.exception` sets it too) with the exception's type, `error_type`, and the innermost
    frames it was raised through, `where`, each as file:function:line."""
    e = _exception(event_dict.pop("exc_info", None))
    if e is not None:
        frames = traceback.walk_tb(e.__traceback__)
        event_dict["error_type"] = type(e).__name__
        event_dict["where"] = [
            f"{os.path.basename(f.f_code.co_filename)}:{f.f_code.co_name}:{line}" for f, line in frames
        ][-WHERE_FRAMES:]
    return event_dict


def configure() -> None:
    """structlog's configuration for this process, applied where the process starts. Where its lines go is left as it
    is: structlog's default, stdout."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            exception_type,
            structlog.processors.JSONRenderer(),
        ]
    )
