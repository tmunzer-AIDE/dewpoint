# SPDX-License-Identifier: Apache-2.0
"""What the worker's logs may hold (engine 2b spec §6.7, §12): no text a run's data could have written, unless it's
proven safe. A secret a plugin makes itself (a token an API issues) is unknown to the run until its output is claimed,
so masking against the secret index proves nothing about a plugin's text. Text written in the plugin's own source is
code, never a run's data: that's what a log may hold.

- A plugin's log line keeps its event, a field's name and a field's value only when each is a constant of the plugin's
  own source (or a boolean or null): a computed event is withheld (`step_event_withheld`), a computed field name
  dropped (`fields_withheld` counts them), and any other value redacted, a number included (a PIN is one). A field
  whose name looks secret is redacted even then.
- A bug in a node is logged by its type and where it was raised; its text only when that's such a constant.
- Temporal's worker logs a failed attempt with its exception, and some of its messages quote an error, heartbeat
  details or an activity's info: its activity records keep only the exact text of one of the SDK's fixed messages and
  a validated code, never what follows the text, nor an exception.

These are the log paths the worker controls: `ctx.log`, its own logs and Temporal's activity records. A plugin that
logs through Python's `logging` or `print`, or a library it calls that logs, is outside them."""

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
from temporalio.exceptions import ApplicationError

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


@functools.cache
def literals(module: str) -> Literals:
    """Every string and number written in the source of `module`'s package, as (type, value): read from its modules'
    code objects (a keyword's name is one too), once per package. What a module's loader can't give as code adds
    nothing, so it's withheld."""
    package = module.rpartition(".")[0] or module
    out: set[tuple[type, object]] = set()
    for name in sorted(n for n in list(sys.modules) if n == package or n.startswith(package + ".")):
        loader = getattr(getattr(sys.modules.get(name), "__spec__", None), "loader", None)
        get_code = getattr(loader, "get_code", None)
        try:
            code = get_code(name) if get_code is not None else None
        except Exception:  # noqa: S112 - a module whose code can't be read proves nothing
            continue
        if code is not None:
            out |= {(type(c), c) for c in _constants([code]) if type(c) in (str, int, float)}
    return frozenset(out)


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


def bug(e: BaseException, known: Literals) -> dict[str, Any]:
    """A bug's log fields: its type and where it was raised; its text only when it's one of the plugin's constants."""
    frames = traceback.StackSummary.extract(traceback.walk_tb(e.__traceback__), lookup_lines=False)
    out: dict[str, Any] = {
        "error_type": type(e).__name__,
        "where": [f"{os.path.basename(f.filename)}:{f.name}:{f.lineno}" for f in frames][-WHERE_FRAMES:],
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
    def filter(self, record: logging.LogRecord) -> bool:
        written = str(record.msg)
        text = next((f for f in _FIXED if written.startswith(f)), WITHHELD_RECORD)
        error = record.exc_info[1] if record.exc_info else None
        if error is not None:
            code = error.type if isinstance(error, ApplicationError) else type(error).__name__
            valid = safe_code(code) or (isinstance(code, str) and len(code) <= CODE_MAX and _CLASS.fullmatch(code))
            text += f" [{code}]" if valid else " [error]"
        record.msg, record.args, record.exc_info, record.exc_text = text, None, None, None
        return True


_WITHHOLD = _Withheld()


def withhold_activity_errors() -> None:
    """Filter, once, the loggers Temporal's worker records attempts with (`temporalio.activity` and its worker's)."""
    for name in ("temporalio.activity", "temporalio.worker._activity"):
        logger = logging.getLogger(name)
        if _WITHHOLD not in logger.filters:
            logger.addFilter(_WITHHOLD)


__all__ = [
    "REDACTED",
    "WITHHELD",
    "WITHHELD_RECORD",
    "StepLog",
    "bug",
    "literals",
    "proven",
    "safe_code",
    "withhold_activity_errors",
]
