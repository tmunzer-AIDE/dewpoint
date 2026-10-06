# SPDX-License-Identifier: Apache-2.0
"""`dewpoint dev run` (engine 2b spec §7.7): it admits a workflow with the source `dev` and, with `--wait`, waits a
bounded time for the end the database records. Exit codes: 0 admitted (or, waited, the run succeeded), 1 it ended
otherwise, 2 it wasn't admitted, 3 the wait ran out. The path itself is covered by tests/apps/worker/test_dev_run.py;
here admission and the wait are stand-ins. No command starts a run itself."""

import base64
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from dewpoint.apps import admission, dev_run
from dewpoint.apps.cli import main as cli
from dewpoint.core.config import get_settings

REQUEST = uuid.UUID(int=7)


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://nobody@localhost/none")
    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
    get_settings.cache_clear()


def answer(monkeypatch: pytest.MonkeyPatch, admitted: Any, ended: Any, seen: dict[str, Any]) -> None:
    async def admit(sessionmaker: Any, keys: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        if isinstance(admitted, Exception):
            raise admitted
        return SimpleNamespace(id=REQUEST, status="queued")

    async def wait_for_end(sessionmaker: Any, tenant_id: Any, request_id: Any, *, within: float, **_: Any) -> Any:
        seen["within"] = within
        return ended

    monkeypatch.setattr(dev_run, "admit", admit)
    monkeypatch.setattr(dev_run, "wait_for_end", wait_for_end)


def run(*args: str) -> Any:
    return CliRunner().invoke(cli.app, ["dev", "run", str(uuid.UUID(int=1)), "--tenant", str(uuid.UUID(int=2)), *args])


@pytest.mark.usefixtures("cli_env")
def test_without_wait_it_prints_the_queued_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}
    answer(monkeypatch, None, None, seen)
    payload = tmp_path / "input.json"
    payload.write_text(json.dumps({"x": 1}))
    result = run("--input", str(payload), "--simulate", "--idempotency-key", "k1")
    assert (result.exit_code, result.output) == (0, f"request {REQUEST} queued\n")
    assert seen == {"tenant_id": uuid.UUID(int=2), "workflow_id": uuid.UUID(int=1), "input": {"x": 1},
                    "simulate": True, "idempotency_key": "k1"}  # fmt: skip


@pytest.mark.usefixtures("cli_env")
@pytest.mark.parametrize(
    ("ended", "code", "said"),
    [
        (dev_run.Ended("run", "succeeded", None, None), 0, f"run {REQUEST} succeeded"),
        (dev_run.Ended("run", "failed", "workflow_failed", "no"), 1, f"run {REQUEST} failed: workflow_failed: no"),
        (dev_run.Ended("request", "dead", "start_refused", None), 1, f"request {REQUEST} dead: start_refused"),
        (None, 3, f"WARNING: request {REQUEST} hasn't ended after 5 s"),
    ],
    ids=["succeeded", "failed", "dead", "wait_ran_out"],
)
def test_waiting_reports_the_end_the_database_records(
    monkeypatch: pytest.MonkeyPatch, ended: Any, code: int, said: str
) -> None:
    seen: dict[str, Any] = {}
    answer(monkeypatch, None, ended, seen)
    result = run("--wait", "5")
    assert result.exit_code == code and said in result.output and seen["within"] == 5.0


@pytest.mark.usefixtures("cli_env")
def test_a_refused_admission_exits_2_with_its_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    answer(monkeypatch, admission.AdmissionRefusedError("workflow_disabled", ["The workflow is disabled."]), None, {})
    result = run()
    assert result.exit_code == 2 and "ERROR: The workflow is disabled." in result.output


@pytest.mark.usefixtures("cli_env")
def test_each_invocation_gets_its_own_idempotency_key_unless_given(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    answer(monkeypatch, None, None, seen)
    run()
    first = seen["idempotency_key"]
    run()
    assert first and seen["idempotency_key"] != first


@pytest.mark.usefixtures("cli_env")
@pytest.mark.parametrize("payload", ["[1, 2]", '"text"', "3"])
def test_an_input_that_isnt_a_json_object_is_refused_before_admission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: str
) -> None:
    seen: dict[str, Any] = {}
    answer(monkeypatch, None, None, seen)
    trigger = tmp_path / "input.json"
    trigger.write_text(payload)
    result = run("--input", str(trigger))
    assert (result.exit_code, result.output) == (2, "ERROR: --input must hold a JSON object\n") and seen == {}


def test_no_command_starts_a_run_itself() -> None:
    """2b-2: every packaged start goes through admission and the dispatcher; `start_run` is a test helper."""
    assert "start_run" not in vars(cli) and "dev_run_version" not in vars(cli)


@pytest.mark.usefixtures("cli_env")
def test_a_retry_of_a_request_past_its_cutoff_shows_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    answer(monkeypatch, dev_run.RequestNotRetainedError(), None, {})
    result = run("--idempotency-key", "old", "--wait", "5")
    assert result.exit_code == 2 and "request_not_retained" in result.output
