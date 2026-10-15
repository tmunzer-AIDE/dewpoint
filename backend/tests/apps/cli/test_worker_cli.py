# SPDX-License-Identifier: Apache-2.0
"""The long-running commands' ends (`worker`, `dispatcher`, `retention`): each stops on SIGTERM or SIGINT and exits
0, the worker 2 when the deployment's record doesn't match (engine 2b spec §2.1) and 3 when the instance failed its
self-check (§2.7), the dispatcher 2 on the same mismatch, retention 1 when its job fails. Its orchestrator restarts it
either way. Each leaves through `stopping.leave` (os._exit after a flush, the owner's ruling X1); an unexpected
exception keeps Typer's traceback and exit 1 (ruling X2)."""

import asyncio
import base64
import os
import signal
from typing import Any, NoReturn

import pytest
from typer.testing import CliRunner

from dewpoint.apps import retention, stopping
from dewpoint.apps.cli import main as cli
from dewpoint.apps.dispatcher import main as dispatcher
from dewpoint.apps.worker.health import WorkerUnhealthyError
from dewpoint.core.config import get_settings
from dewpoint.core.platform.service import EnvironmentNotRecordedError
from tests.support.logs import records


@pytest.fixture
def left(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The codes the command left with through `stopping.leave`, each ending it as the suite's guard does."""
    codes: list[int] = []

    def leave(code: int) -> NoReturn:
        codes.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(stopping, "_exit", leave)
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://nobody@localhost/none")
    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
    get_settings.cache_clear()
    return codes


async def stopped(*args: Any, stop_requested: asyncio.Event, **kwargs: Any) -> None:
    """A process asked to stop: the command's own SIGTERM handler sets the event it was given."""
    assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL  # or the signal would end the test's process
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(stop_requested.wait(), 10)


def test_the_worker_stops_on_sigterm_and_exits_0(monkeypatch: pytest.MonkeyPatch, left: list[int]) -> None:
    """Compose's stop: the signal is logged, the worker stops, and the process leaves with 0."""

    async def run_worker(settings: Any, stop_requested: asyncio.Event) -> None:
        await stopped(stop_requested=stop_requested)

    monkeypatch.setattr(cli, "run_worker", run_worker)
    result = CliRunner().invoke(cli.app, ["worker"])
    assert (result.exit_code, left) == (0, [0])
    [line] = records(result.output.splitlines())
    assert (line["event"], line["signal"]) == ("stop_requested", "SIGTERM")


@pytest.mark.parametrize(
    ("error", "code"),
    [(EnvironmentNotRecordedError(), 2), (WorkerUnhealthyError("This worker failed its self-check."), 3)],
)
def test_the_worker_exits_with_its_reason(
    monkeypatch: pytest.MonkeyPatch, left: list[int], error: Exception, code: int
) -> None:
    async def run_worker(settings: Any, stop_requested: asyncio.Event) -> None:
        raise error

    monkeypatch.setattr(cli, "run_worker", run_worker)
    result = CliRunner().invoke(cli.app, ["worker"])
    assert (result.exit_code, result.output, left) == (code, f"ERROR: {error}\n", [code])


def test_the_dispatcher_stops_on_sigterm_and_exits_0(monkeypatch: pytest.MonkeyPatch, left: list[int]) -> None:
    monkeypatch.setattr(dispatcher, "run", stopped)
    result = CliRunner().invoke(cli.app, ["dispatcher"])
    assert (result.exit_code, left) == (0, [0])


def test_the_dispatcher_exits_2_on_a_deployment_it_wasnt_recorded_for(
    monkeypatch: pytest.MonkeyPatch, left: list[int]
) -> None:
    async def unrecorded(*args: Any, **kwargs: Any) -> None:
        raise EnvironmentNotRecordedError()

    monkeypatch.setattr(dispatcher, "run", unrecorded)
    result = CliRunner().invoke(cli.app, ["dispatcher"])
    assert (result.exit_code, left) == (2, [2])


def test_the_retention_job_stops_on_sigterm_and_exits_0(monkeypatch: pytest.MonkeyPatch, left: list[int]) -> None:
    monkeypatch.setattr(retention, "run", stopped)
    result = CliRunner().invoke(cli.app, ["retention"])
    assert (result.exit_code, left) == (0, [0])


def test_a_failed_retention_job_says_so_and_exits_1(monkeypatch: pytest.MonkeyPatch, left: list[int]) -> None:
    async def failing(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("the database went away")

    monkeypatch.setattr(retention, "run", failing)
    result = CliRunner().invoke(cli.app, ["retention"])
    assert (result.exit_code, result.output, left) == (1, "retention sweep failed: ConnectionError\n", [1])


def test_an_unexpected_failure_keeps_its_traceback_and_exit_1(monkeypatch: pytest.MonkeyPatch, left: list[int]) -> None:
    """Ruling X2: the normal path, which Typer renders; `leave` isn't reached."""

    async def broken(settings: Any, stop_requested: asyncio.Event) -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr(cli, "run_worker", broken)
    result = CliRunner().invoke(cli.app, ["worker"])
    assert (result.exit_code, type(result.exception), left) == (1, RuntimeError, [])
