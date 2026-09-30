# SPDX-License-Identifier: Apache-2.0
"""`dewpoint dev run`'s exit codes: 0 when the run succeeded, 1 when it ended otherwise or Temporal refused it, 2 when
it wasn't admitted, 3 when Temporal never confirmed the start. The run itself is covered by
tests/apps/worker/test_dev_run.py; here Temporal and the run are stand-ins."""

import base64
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from dewpoint.apps.runs import NotAdmissibleError, StartRefusedError, StartUncertainError
from dewpoint.core.config import get_settings
from dewpoint.engine.runtime.activities import RunResult

RUN = uuid.UUID(int=7)


class _Client:
    @staticmethod
    async def connect(*args: Any, **kwargs: Any) -> "_Client":
        return _Client()


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://nobody@localhost/none")
    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
    monkeypatch.setattr(cli, "Client", _Client)
    monkeypatch.setattr(cli, "verify_environment", _recorded)  # the check itself: tests/apps/test_environment.py
    get_settings.cache_clear()


async def _recorded(*args: Any) -> None:
    """A deployment whose record matches: the CLI's Temporal commands check it before connecting (2b spec §2.1)."""


def _answer(monkeypatch: pytest.MonkeyPatch, outcome: RunResult | Exception, seen: dict[str, Any]) -> None:
    async def dev_run_version(settings: Any, client: Any, **kwargs: Any) -> tuple[uuid.UUID, RunResult | None]:
        seen.update(kwargs)
        if isinstance(outcome, Exception):
            raise outcome
        return RUN, outcome if kwargs["wait"] else None

    monkeypatch.setattr(cli, "dev_run_version", dev_run_version)


@pytest.mark.usefixtures("cli_env")
def test_a_succeeded_run_prints_its_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}
    _answer(monkeypatch, RunResult("succeeded", {"v": 2}), seen)
    payload = tmp_path / "trigger.json"
    payload.write_text(json.dumps({"x": 1}))
    tenant, version = uuid.uuid4(), uuid.uuid4()
    result = CliRunner().invoke(
        cli.app, ["dev", "run", str(version), "--tenant", str(tenant), "--input", str(payload), "--simulate"]
    )
    assert result.exit_code == 0, result.output
    assert f"run {RUN}" in result.output and '"status": "succeeded"' in result.output
    assert seen == {"tenant_id": tenant, "version_id": version, "trigger": {"x": 1}, "simulate": True, "wait": True}


@pytest.mark.usefixtures("cli_env")
def test_a_run_that_did_not_succeed_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer(monkeypatch, RunResult("failed", error={"code": "workflow_failed", "message": "no"}), {})
    result = CliRunner().invoke(cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4())])
    assert result.exit_code == 1 and '"code": "workflow_failed"' in result.output


@pytest.mark.usefixtures("cli_env")
def test_a_refused_run_exits_2_with_its_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer(monkeypatch, NotAdmissibleError(["the workflow is disabled"]), {})
    result = CliRunner().invoke(cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4())])
    assert result.exit_code == 2 and "ERROR: the workflow is disabled" in result.output


@pytest.mark.usefixtures("cli_env")
def test_no_wait_prints_only_the_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer(monkeypatch, RunResult("succeeded"), {})
    args = ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4()), "--no-wait"]
    result = CliRunner().invoke(cli.app, args)
    assert (result.exit_code, result.output.strip()) == (0, f"run {RUN}")


@pytest.mark.usefixtures("cli_env")
@pytest.mark.parametrize(
    ("error", "code", "said"),
    [
        (StartRefusedError("Temporal refused the run (INVALID_ARGUMENT)."), 1, "ERROR: Temporal refused the run"),
        (StartUncertainError(RUN), 3, f"WARNING: Temporal didn't confirm or refuse run {RUN}"),
    ],
)
def test_a_start_temporal_refused_or_never_confirmed(
    monkeypatch: pytest.MonkeyPatch, error: Exception, code: int, said: str
) -> None:
    _answer(monkeypatch, error, {})
    result = CliRunner().invoke(cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4())])
    assert result.exit_code == code and said in result.output


@pytest.mark.usefixtures("cli_env")
@pytest.mark.parametrize("payload", ["[1, 2]", '"text"', "3"])
def test_an_input_that_isnt_a_json_object_is_refused_before_anything_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: str
) -> None:
    """2a-3a's final review, M4: a trigger that isn't an object (a list, a string) left the run failing its first
    workflow task forever, so it hung. The CLI refuses it."""
    seen: dict[str, Any] = {}
    _answer(monkeypatch, RunResult("succeeded", {}), seen)
    trigger = tmp_path / "trigger.json"
    trigger.write_text(payload)
    result = CliRunner().invoke(
        cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4()), "--input", str(trigger)]
    )
    assert (result.exit_code, result.output) == (2, "ERROR: --input must hold a JSON object\n") and seen == {}
