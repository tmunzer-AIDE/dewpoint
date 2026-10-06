# SPDX-License-Identifier: Apache-2.0
"""Every process's log configuration: an exception is logged by its type and the innermost frames it was raised
through, never its text nor a frame's local variables."""

import json
from typing import Any

import structlog

from dewpoint.core import logs
from tests.support.logs import rendered

SECRET = "s3cr3t-value-91be"


def _fails(depth: int) -> None:
    secret = SECRET
    if depth:
        _fails(depth - 1)
    raise KeyError(secret)


def _records(lines: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in lines]


def test_an_exception_is_logged_by_its_type_and_where_it_was_raised() -> None:
    with rendered() as lines:
        logs.configure()
        try:
            _fails(0)
        except KeyError as e:
            structlog.get_logger("t").error("failed", exc_info=e)
    assert SECRET not in "\n".join(lines())
    [record] = _records(lines())
    assert record["event"] == "failed" and record["level"] == "error"
    assert record["error_type"] == "KeyError" and "exception" not in record and "exc_info" not in record
    assert [frame.rsplit(":", 1)[0] for frame in record["where"]] == [
        "test_logs.py:test_an_exception_is_logged_by_its_type_and_where_it_was_raised",
        "test_logs.py:_fails",
    ]


def test_only_the_innermost_frames_are_named() -> None:
    with rendered() as lines:
        logs.configure()
        try:
            _fails(20)
        except KeyError as e:
            structlog.get_logger("t").error("failed", exc_info=e)
    assert SECRET not in "\n".join(lines())
    [record] = _records(lines())
    assert len(record["where"]) == logs.WHERE_FRAMES
    assert all(frame.startswith("test_logs.py:_fails:") for frame in record["where"])


def test_the_current_exception_is_named_and_none_adds_nothing() -> None:
    log = structlog.get_logger("t")
    with rendered() as lines:
        logs.configure()
        try:
            _fails(0)
        except KeyError:
            log.exception("caught")
            log.error("caught", exc_info=True)
        log.error("calm", exc_info=True)
    assert SECRET not in "\n".join(lines())
    caught, also, calm = _records(lines())
    assert caught["error_type"] == also["error_type"] == "KeyError"
    assert caught["where"][-1].startswith("test_logs.py:_fails:")
    assert not {"error_type", "where", "exception", "exc_info"} & calm.keys()
