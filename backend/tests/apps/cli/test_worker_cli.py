# SPDX-License-Identifier: Apache-2.0
"""`dewpoint worker`'s exits: 2 when the deployment's record doesn't match (engine 2b spec §2.1), 3 when the instance
failed its self-check (§2.7). Its orchestrator restarts it either way."""

import base64
from typing import Any

import pytest
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from dewpoint.apps.worker.health import WorkerUnhealthyError
from dewpoint.core.config import get_settings
from dewpoint.core.platform.service import EnvironmentNotRecordedError


@pytest.mark.parametrize(
    ("error", "code"),
    [(EnvironmentNotRecordedError(), 2), (WorkerUnhealthyError("This worker failed its self-check."), 3)],
)
def test_the_worker_exits_with_its_reason(monkeypatch: pytest.MonkeyPatch, error: Exception, code: int) -> None:
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://nobody@localhost/none")
    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
    get_settings.cache_clear()

    async def run_worker(settings: Any) -> None:
        raise error

    monkeypatch.setattr(cli, "run_worker", run_worker)
    result = CliRunner().invoke(cli.app, ["worker"])
    assert (result.exit_code, result.output) == (code, f"ERROR: {error}\n")
