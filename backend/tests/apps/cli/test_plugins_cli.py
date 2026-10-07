# SPDX-License-Identifier: Apache-2.0
import base64
import os

import pytest
from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.apps.plugin_loader import installed_plugins
from dewpoint.core.config import get_settings


@pytest.fixture
def cli_env(pg_url, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", pg_url)
    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_entry_points_expose_the_first_party_plugins() -> None:
    assert [p.name for p in installed_plugins()] == ["flow", "mist", "slack", "teams"]


def test_plugins_sync_is_idempotent(cli_env) -> None:  # type: ignore[no-untyped-def]
    runner = CliRunner()
    first = runner.invoke(app, ["plugins", "sync"])
    assert first.exit_code == 0, first.output
    installed = sum(len(p.nodes) for p in installed_plugins())  # flow's 11 and a node per curated Mist operation
    assert installed > 11 and f"added {installed}, unchanged 0" in first.output
    second = runner.invoke(app, ["plugins", "sync"])
    assert second.exit_code == 0 and f"added 0, unchanged {installed}" in second.output
    listed = runner.invoke(app, ["plugins", "list"])
    assert "flow.if@1 active" in listed.output and "mist.org_wlans.get@1 active" in listed.output


def test_lifecycle_commands(cli_env) -> None:  # type: ignore[no-untyped-def]
    runner = CliRunner()
    assert runner.invoke(app, ["plugins", "sync"]).exit_code == 0
    r = runner.invoke(app, ["lifecycle", "deprecate", "--node-type", "flow.wait_until@1"])
    assert r.exit_code == 0 and "deprecated" in r.output
    r = runner.invoke(app, ["lifecycle", "retire", "--node-type", "flow.wait_until@1"])
    assert r.exit_code == 0 and "retired" in r.output
    assert runner.invoke(app, ["plugins", "sync"]).exit_code == 0  # a retired type may stay installed
    assert runner.invoke(app, ["lifecycle", "retire", "--node-type", "flow.nope@1"]).exit_code == 2
    assert runner.invoke(app, ["lifecycle", "retire"]).exit_code == 2
