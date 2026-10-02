# SPDX-License-Identifier: Apache-2.0
"""What the worker's logs may hold (engine 2b spec §6.7, §12): no text a run's data could have written, unless it's
proven safe. A secret a plugin makes itself (a token an API issues) is unknown to the run until its output is claimed,
so masking against the secret index proves nothing about a plugin's text. Text written in the plugin's own source is
code, never a run's data: that's what a log may hold.

- A plugin's log line keeps its event, a field's name and a field's value only when each is a constant of the plugin's
  own source (or a boolean or null): a computed event is withheld (`step_event_withheld`), a computed field name
  dropped (`fields_withheld` counts them), and any other value redacted, a number included (a PIN is one). A field
  whose name looks secret is redacted even then.
- A bug in a node is logged by its type and where it was raised; its text only when that's such a constant. A class
  name is text too: it's shown when the class is a builtin or its module's code declares that name, else as UNNAMED;
  a frame is named only when its code was compiled from its module's source (a function renamed at run time isn't).
- Temporal's worker logs a failed attempt with its exception, and some of its messages quote an error, heartbeat
  details or an activity's info: its activity records keep only the exact text of one of the SDK's fixed messages,
  never what follows it, nor an error's code or class, nor an exception.

These are the log paths the worker controls: `ctx.log`, its own logs and Temporal's activity records. A plugin that
logs through Python's `logging` or `print`, or a library it calls that logs, is outside them."""

import builtins
import functools
import logging
import os
import re
import sys
import traceback
import types
from collections.abc import Iterable, Iterator
from typing import Any

import structlog

REDACTED = "[redacted]"
WITHHELD = "step_event_withheld"
CODE_MAX = 64
_CODE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")  # a step's code: `echo_failed`, `mist.rate_limited`
_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")  # an exception's class
WHERE_FRAMES = 8  # the innermost frames a bug's log names
_SECRET = re.compile(r"password|secret|token|credential|authorization|api_?key", re.IGNORECASE)

type Literals = frozenset[tuple[type, object]]


def _constants(items: Iterable[object]) -> Iterator[object]:
    for c in items:
        if isinstance(c, types.CodeType):
            yield from _constants(c.co_consts)
        elif isinstance(c, tuple | frozenset):
            yield from _constants(c)
        else:
            yield c


def _codes(code: types.CodeType) -> Iterator[types.CodeType]:
    yield code
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            yield from _codes(c)


@functools.cache
def _package(module: str) -> tuple[Literals, frozenset[tuple[str, str, int]]]:
    """What the source of `module`'s package holds, read from its modules' code objects once per package: every string
    and number written in it, as (type, value) (a keyword's or a class's name is one too), and every function's code
    as (file, name, first line). What a module's loader can't give as code adds nothing, so it's withheld."""
    package = module.rpartition(".")[0] or module
    found: set[tuple[type, object]] = set()
    functions: set[tuple[str, str, int]] = set()
    for name in sorted(n for n in list(sys.modules) if n == package or n.startswith(package + ".")):
        loader = getattr(getattr(sys.modules.get(name), "__spec__", None), "loader", None)
        get_code = getattr(loader, "get_code", None)
        try:
            code = get_code(name) if get_code is not None else None
        except Exception:  # noqa: S112 - a module whose code can't be read proves nothing
            continue
        if code is not None:
            found |= {(type(c), c) for c in _constants([code]) if type(c) in (str, int, float)}
            functions |= {(c.co_filename, c.co_name, c.co_firstlineno) for c in _codes(code)}
    return frozenset(found), frozenset(functions)


def literals(module: str) -> Literals:
    """Every string and number written in the source of `module`'s package, as (type, value)."""
    return _package(module)[0]


def safe_code(code: object) -> bool:
    """A code's shape: a dotted lowercase identifier of at most CODE_MAX characters, nothing a message could hide in."""
    return isinstance(code, str) and len(code) <= CODE_MAX and _CODE.fullmatch(code) is not None


def proven(value: object, known: Literals) -> bool:
    """`value` is safe to log: a boolean, null, or one of the plugin's own constants."""
    return (
        value is None or isinstance(value, bool) or (type(value) in (str, int, float) and (type(value), value) in known)
    )


class StepLog:
    """A plugin step's `ctx.log`, bound to the step's ids: it logs only what its plugin's code wrote."""

    def __init__(self, known: Literals, **ids: str) -> None:
        self._log = structlog.get_logger("dewpoint.step").bind(**ids)
        self._known = known

    def _line(self, event: str, fields: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        out: dict[str, Any] = {}
        for name, value in fields.items():
            if not proven(name, self._known):
                out["fields_withheld"] = out.get("fields_withheld", 0) + 1
            elif _SECRET.search(name) or not proven(value, self._known):
                out[name] = REDACTED
            else:
                out[name] = value
        return (event if isinstance(event, str) and proven(event, self._known) else WITHHELD), out

    def info(self, event: str, **fields: Any) -> None:
        name, kept = self._line(event, fields)
        self._log.info(name, **kept)

    def warning(self, event: str, **fields: Any) -> None:
        name, kept = self._line(event, fields)
        self._log.warning(name, **kept)


UNNAMED = "an exception whose class name isn't shown"
UNNAMED_FRAME = "withheld"


def error_class(e: BaseException) -> str:
    """The class's name when it's proven to be code: a builtin's, or a name its module's code declares (a class made
    at run time can be named with anything, a fresh token included); UNNAMED otherwise."""
    cls, name = type(e), type(e).__name__
    if not (isinstance(name, str) and len(name) <= CODE_MAX and _CLASS.fullmatch(name)):
        return UNNAMED
    if cls.__module__ == "builtins":
        return name if getattr(builtins, name, None) is cls else UNNAMED
    module = cls.__module__
    return name if isinstance(module, str) and (str, name) in literals(module) else UNNAMED


def _frame(frame: types.FrameType, line: int | None) -> str:
    """A frame's file, function and line, when its code was compiled from its module's source; else UNNAMED_FRAME."""
    code, module = frame.f_code, frame.f_globals.get("__name__")
    if isinstance(module, str) and (code.co_filename, code.co_name, code.co_firstlineno) in _package(module)[1]:
        return f"{os.path.basename(code.co_filename)}:{code.co_name}:{line}"
    return UNNAMED_FRAME


def bug(e: BaseException, known: Literals) -> dict[str, Any]:
    """A bug's log fields: its type and where it was raised, as far as they're proven to be code; its text only when
    it's one of the plugin's constants."""
    out: dict[str, Any] = {
        "error_type": error_class(e),
        "where": [_frame(f, line) for f, line in traceback.walk_tb(e.__traceback__)][-WHERE_FRAMES:],
    }
    if str(e) and proven(str(e), known):
        out["error"] = str(e)
    return out


# The SDK's activity messages, each kept exactly as written here: a record is matched by its start, and only this
# text is kept, never what follows it (an activity's info, an error's text, heartbeat details). Longest first, so a
# message matches its own text, not a shorter one's.
_FIXED = tuple(
    sorted(
        (
            "Completing activity as failed",
            "Completing as cancelled",
            "Completing asynchronously",
            "Completing as failure due to unhandled cancel error produced by activity pause",
            "Completing as failure due to unhandled cancel error produced by activity reset",
            "Completing activity with completion",
            "Starting activity",
            "Running activity",
            "Cancelling activity because failed recording heartbeat",
            "Cancelling activity",
            "Failed completing activity task",
            "Failed recording heartbeat (activity already done, cannot error)",
            "Final heartbeat task didn't trap error",
        ),
        key=len,
        reverse=True,
    )
)
WITHHELD_RECORD = "Activity record withheld"


class _Withheld(logging.Filter):
    """Only the exact fixed text: no code (its shape proves nothing about where it came from: a lowercase identifier
    made at run time looks like any other), no class, no exception. The step's code is in its projection."""

    def filter(self, record: logging.LogRecord) -> bool:
        written = str(record.msg)
        record.msg = next((f for f in _FIXED if written.startswith(f)), WITHHELD_RECORD)
        record.args, record.exc_info, record.exc_text = None, None, None
        return True


_WITHHOLD = _Withheld()


def withhold_activity_errors() -> None:
    """Filter, once, the loggers Temporal's worker records attempts with (`temporalio.activity` and its worker's)."""
    for name in ("temporalio.activity", "temporalio.worker._activity"):
        logger = logging.getLogger(name)
        if _WITHHOLD not in logger.filters:
            logger.addFilter(_WITHHOLD)


__all__ = [
    "UNNAMED",
    "UNNAMED_FRAME",
    "REDACTED",
    "WITHHELD",
    "WITHHELD_RECORD",
    "StepLog",
    "bug",
    "error_class",
    "literals",
    "proven",
    "safe_code",
    "withhold_activity_errors",
]
