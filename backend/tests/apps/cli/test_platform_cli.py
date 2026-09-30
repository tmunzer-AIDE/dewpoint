# SPDX-License-Identifier: Apache-2.0
"""`dewpoint platform init-environment` records what this deployment is, once (engine 2b spec §2.1). Compose's migrate
step runs it; running it again with the same values changes nothing."""

import base64

import pytest
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from dewpoint.core.config import get_settings


@pytest.fixture
def owner_env(monkeypatch: pytest.MonkeyPatch, pg_url: str) -> None:
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", pg_url)
    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
    monkeypatch.delenv("DEWPOINT_ENVIRONMENT", raising=False)
    monkeypatch.delenv("DEWPOINT_TEMPORAL_NAMESPACE", raising=False)
    get_settings.cache_clear()


@pytest.mark.usefixtures("owner_env")
def test_a_deployment_is_production_unless_told_otherwise_and_records_it_once() -> None:
    first = CliRunner().invoke(cli.app, ["platform", "init-environment"])
    again = CliRunner().invoke(cli.app, ["platform", "init-environment", "--environment", "production"])
    assert first.exit_code == 0
    assert first.output == "this deployment is production, with the Temporal namespace `default`\n"
    assert again.exit_code == 0
    other = CliRunner().invoke(cli.app, ["platform", "init-environment", "--environment", "development"])
    assert other.exit_code == 2
    assert "recorded as production" in other.output


@pytest.mark.usefixtures("owner_env")
def test_a_development_setup_says_so_with_its_own_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEWPOINT_ENVIRONMENT", "development")
    get_settings.cache_clear()
    result = CliRunner().invoke(cli.app, ["platform", "init-environment", "--temporal-namespace", "dewpoint-ci"])
    assert (result.exit_code, result.output) == (
        0,
        "this deployment is development, with the Temporal namespace `dewpoint-ci`\n",
    )
