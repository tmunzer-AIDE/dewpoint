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


@pytest.mark.usefixtures("owner_env")
def test_the_ingress_capacity_is_set_then_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEWPOINT_ENVIRONMENT", "development")
    get_settings.cache_clear()
    assert CliRunner().invoke(cli.app, ["platform", "init-environment"]).exit_code == 0
    given = ["platform", "set-ingress-capacity", "--starts-per-s", "8", "--headroom", "0.5", "--queue-wait-s", "300"]
    set_ = CliRunner().invoke(cli.app, given)
    said = "ingress capacity: 8.0 starts a second measured, 0.5 of them for ingress, a 300 s queue: a tenant's queue "
    assert (set_.exit_code, set_.output) == (0, said + "holds 1200 requests\n")
    bad = CliRunner().invoke(cli.app, ["platform", "set-ingress-capacity", "--starts-per-s", "8", "--headroom", "2"])
    assert bad.exit_code == 2 and "ingress capacity" in bad.output
    unset = CliRunner().invoke(cli.app, ["platform", "set-ingress-capacity", "--unset"])
    assert (unset.exit_code, unset.output) == (0, "ingress capacity unset: the development-only rates and cap\n")
