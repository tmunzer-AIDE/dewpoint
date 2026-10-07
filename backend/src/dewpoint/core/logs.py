# SPDX-License-Identifier: Apache-2.0
"""How every process logs (the API, the worker, the dispatcher, ingress, each admin command): one JSON object per
line, and an exception by its type and the innermost frames it was raised through, never by a value. structlog's
defaults render a rich traceback with every frame's local variables (a password a route read from its body, a token,
a response's body), and an exception's text can quote whatever it was given: neither is logged.

What this covers, once `configure` has run:
- structlog's lines, on stdout.
- every record of a standard library logger that reaches the root logger, on stderr: uvicorn's (its own configuration
  gives way), SQLAlchemy's, Temporal's. Its exception is named by its type and where; an exception among its message's
  arguments, or as its message, by its type. Of its `extra=` fields, only the ones the engine logs by (`EXTRAS`);
  the others are a library's to fill (Temporal's workflow logger adds the workflow's info).
  A record is written once, however often the process is configured.
- an ASGI app's lifespan failure, behind `LifespanFailures`: Starlette sends the server the formatted traceback.

What it doesn't cover: text a library writes into a message itself (asyncio's default exception handler writes the
exception's repr into "Task exception was never retrieved"), a library's own message that quotes a value, and output
that isn't logging (an uncaught exception's traceback, printed by Python's or Typer's hook).

A frame is named by its file, function and line, which are its code's. A plugin step's bug is logged by the worker's
own, stricter, rules (dewpoint.apps.worker.logs)."""

import logging
import os
import sys
import traceback
from collections.abc import Mapping
from typing import TextIO

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from structlog.typing import EventDict, Processor, WrappedLogger

WHERE_FRAMES = 8  # the innermost frames an exception's log names
UVICORN = ("uvicorn", "uvicorn.access")  # the loggers uvicorn's own configuration gives handlers of its own
# A record's `extra=` fields written, the ones the engine logs by: a workflow bug's type and where (engine 2b spec
# §6.7), and an undelivered budget signal's workflow, an id the server built, and its name. No other is written.
EXTRAS = ("error_type", "where", "signal_to", "signal_name")

log = structlog.get_logger(__name__)


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


def _typed(value: object) -> object:
    return type(value).__name__ if isinstance(value, BaseException) else value


def _message(logger: WrappedLogger, method: str, event_dict: EventDict) -> EventDict:
    """A standard library record's message, from its template and its arguments: an exception among them is named by
    its type, and so is a message that is an exception. Arguments the template doesn't fit leave it as written (the
    standard library's report of a bad record would quote them). The record's logger is named too."""
    record: logging.LogRecord = event_dict["_record"]
    args = event_dict.pop("positional_args", None)
    if isinstance(record.msg, BaseException):
        event_dict["event"] = type(record.msg).__name__
    elif args:
        typed = {k: _typed(v) for k, v in args.items()} if isinstance(args, Mapping) else tuple(_typed(a) for a in args)
        try:
            event_dict["event"] = str(record.msg) % typed
        except (TypeError, ValueError, KeyError):
            pass
    event_dict["logger"] = record.name
    return event_dict


class _Stderr(logging.StreamHandler[TextIO]):
    """The process's stderr as it is when a record is written: a test, or a server, may have replaced it since."""

    @property
    def stream(self) -> TextIO:
        return sys.stderr

    @stream.setter
    def stream(self, value: TextIO) -> None:
        pass


_SHARED: list[Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
]
_HANDLER = _Stderr()
_HANDLER.setFormatter(
    structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[*_SHARED, _message, structlog.stdlib.ExtraAdder(allow=EXTRAS), exception_type],
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, structlog.processors.JSONRenderer()],
        use_get_message=False,
        pass_foreign_args=True,
    )
)


def configure() -> None:
    """This process's logging, applied where the process starts: structlog's lines go where structlog's default puts
    them, stdout; the standard library's records, uvicorn's included, to stderr, through the root logger. A uvicorn
    logger with handlers of its own gives them up; one uvicorn left without any nor propagation stays silent (uvicorn
    writes an access line only while its logger has a handler: `--no-access-log` is that)."""
    structlog.configure(processors=[*_SHARED, exception_type, structlog.processors.JSONRenderer()])
    root = logging.getLogger()
    if _HANDLER not in root.handlers:
        root.addHandler(_HANDLER)
    for name in UVICORN:
        logger = logging.getLogger(name)
        if logger.handlers:
            logger.handlers.clear()
            logger.propagate = True


_FAILED = ("lifespan.startup.failed", "lifespan.shutdown.failed")


class LifespanFailures:
    """An ASGI app's lifespan failure, logged by its phase and its exception's type and where it was raised. Starlette
    sends the server the formatted traceback as the failure's message, the exception's text and its causes' included,
    and uvicorn logs that message as it is: it's sent without one (the server still learns of the failure from its
    type), and the exception Starlette re-raises is logged here and raised on unchanged."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "lifespan":
            await self.app(scope, receive, send)
            return
        phase, failed = "startup", False  # this lifespan's

        async def forward(message: Message) -> None:
            nonlocal phase, failed
            if message["type"] in _FAILED:
                failed, message = True, {"type": message["type"]}
            await send(message)
            if message["type"] == "lifespan.startup.complete":
                phase = "shutdown"

        try:
            await self.app(scope, receive, forward)
        except BaseException as e:
            if failed:
                log.error("lifespan_failed", phase=phase, exc_info=e)
            raise
