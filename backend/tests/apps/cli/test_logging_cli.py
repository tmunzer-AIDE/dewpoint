# SPDX-License-Identifier: Apache-2.0
"""Every process the CLI starts (the worker, the dispatcher, ingress, each admin command) logs an exception by its
type and where it was raised, never a frame's local variables nor the exception's text."""

import json
from typing import Any

import pytest
import structlog
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from tests.support.logs import rendered

TOKEN = "tok-live-3a9e7d1c"


async def _crashes(settings: Any) -> None:
    token = TOKEN
    try:
        if token:
            raise ConnectionError(f"refused {token}")
    except ConnectionError:
        structlog.get_logger("dewpoint.test").exception("process_failed")


@pytest.mark.parametrize(
    ("command", "run"),
    [("worker", "dewpoint.apps.cli.main.run_worker"), ("dispatcher", "dewpoint.apps.dispatcher.main.run")],
)
def test_a_process_logs_an_exception_by_its_type_only(monkeypatch: pytest.MonkeyPatch, command: str, run: str) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: None)
    monkeypatch.setattr(run, _crashes)
    with rendered() as lines:
        result = CliRunner().invoke(cli.app, [command])
    assert result.exit_code == 0, result.output
    assert TOKEN not in "\n".join(lines()) + result.output
    [record] = [json.loads(line) for line in lines()]
    assert record["event"] == "process_failed" and record["error_type"] == "ConnectionError"
    assert [frame.rsplit(":", 1)[0] for frame in record["where"]] == ["test_logging_cli.py:_crashes"]
