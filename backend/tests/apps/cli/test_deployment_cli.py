# SPDX-License-Identifier: Apache-2.0
"""`dewpoint deployment`: `set-current` makes this build (or the one named) the one new runs start on, and `status`
lists every version. The calls themselves are covered by tests/apps/worker/test_deployment.py, on Temporal's dev
server; here Temporal is a stand-in."""

from typing import Any

import pytest
from typer.testing import CliRunner

import dewpoint
from dewpoint.apps.cli import main as cli
from dewpoint.apps.worker.deployment import Deployment, Version
from dewpoint.engine.runtime.build import build_id
from tests.apps.cli.test_dev_run_cli import cli_env  # noqa: F401  (a fixture)


@pytest.mark.usefixtures("cli_env")
def test_set_current_defaults_to_this_build(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, float]] = []

    async def set_current(client: Any, build: str, *, wait_s: float) -> None:
        seen.append((build, wait_s))

    monkeypatch.setattr(cli, "set_current", set_current)
    this = build_id(dewpoint.__version__)
    first = CliRunner().invoke(cli.app, ["deployment", "set-current"])
    second = CliRunner().invoke(cli.app, ["deployment", "set-current", "--build-id", "b-2", "--wait", "5"])
    assert (first.exit_code, first.output) == (0, f"current: {this}\n")
    assert (second.exit_code, second.output) == (0, "current: b-2\n")
    assert seen == [(this, 60.0), ("b-2", 5.0)]


@pytest.mark.usefixtures("cli_env")
def test_status_lists_every_version(monkeypatch: pytest.MonkeyPatch) -> None:
    async def describe(client: Any) -> Deployment:
        return Deployment("b-2", [Version("b-1", "draining"), Version("b-2", "current")])

    monkeypatch.setattr(cli, "describe", describe)
    result = CliRunner().invoke(cli.app, ["deployment", "status"])
    assert (result.exit_code, result.output) == (0, "current: b-2\nb-1  draining\nb-2  current\n")
