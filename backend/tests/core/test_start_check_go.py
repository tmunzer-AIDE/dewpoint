# SPDX-License-Identifier: Apache-2.0
"""D12's start-check tests that need Dewpoint's database (deploy/temporal/internal/startcheck/startcheck_db_test.go),
run against this suite's own database (the 2b-4b M4 start-check slice): migrated to head with its logins, as every
database test's is; one eligible request set up with the function tests' own `starting`; and, after, that request
removed with every other test's rows (`clean_db`) and the start check's login restored, whatever the Go tests did to it.

Opt-in, as it needs Go and a verified module cache (the backend's CI job has neither):

    DEWPOINT_GO_DB=1 GOMODCACHE=<verified module cache> PYTHONPATH=src .venv/bin/pytest -p no:cacheprovider -n 0 \\
        tests/core/test_start_check_go.py

Once opted in, nothing it needs is optional: a missing `go` or module cache fails the run, the Go tests are told every
setting is required (`DEWPOINT_TEST_PG_REQUIRED`), and any Go test that skips fails it. Offline only: GOPROXY=off,
GOFLAGS=-mod=readonly, GOTOOLCHAIN=local."""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import asyncpg
import pytest

from tests.apps.test_admission import ready  # noqa: F401 - the fixture
from tests.conftest import _url_for
from tests.core.test_start_check_function import _dsn, starting

pytestmark = [
    pytest.mark.skipif(not os.environ.get("DEWPOINT_GO_DB"), reason="needs Go and a module cache (DEWPOINT_GO_DB=1)"),
    pytest.mark.usefixtures("development_deployment"),  # admission needs a recorded environment
]
TEMPORAL = Path(__file__).resolve().parents[3] / "deploy" / "temporal"
ALLOW = "TestDatabaseAnEligibleRequestIsAllowedAndOnlyByItsOwnStartRequestID"
LOGIN = "t_dewpoint_start_check"  # the suite's LOGIN member of dewpoint_start_check (`TEST_ROLES`)


def _outcomes(stdout: str) -> dict[str, str]:
    """Each Go test's last outcome, from `go test -json`: pass, fail or skip."""
    found: dict[str, str] = {}
    for line in stdout.splitlines():
        if line.startswith("{"):
            event = json.loads(line)
            if event.get("Test") and event.get("Action") in ("pass", "fail", "skip"):
                found[event["Test"]] = event["Action"]
    return found


def _required() -> str:
    """`go`, with the verified module cache: required here, never a reason to skip."""
    go, cache = shutil.which("go"), os.environ.get("GOMODCACHE", "")
    assert go is not None, "`go` isn't on PATH: required here"
    assert cache and Path(cache).is_dir(), "GOMODCACHE names the verified module cache: required here"
    return go


async def _login_restored(pg_url: str) -> None:
    c = await asyncpg.connect(_dsn(pg_url))
    try:
        await c.execute(f"ALTER ROLE {LOGIN} LOGIN")
    finally:
        await c.close()


async def test_d12s_start_check_against_this_database_every_go_test_runs_and_passes(
    pg_url,
    owner_sessionmaker,
    api_sessionmaker,
    ready,  # noqa: F811
) -> None:
    go = _required()
    workflow_id, start_request_id, _ = await starting(owner_sessionmaker, api_sessionmaker, ready)
    env = {
        **os.environ,
        "GOPROXY": "off",
        "GOFLAGS": "-mod=readonly",
        "GOTOOLCHAIN": "local",
        "DEWPOINT_TEST_PG_REQUIRED": "1",
        "DEWPOINT_TEST_PG_DSN": f"{_dsn(pg_url)}?sslmode=disable",
        "DEWPOINT_TEST_PG_CHECK_DSN": f"{_dsn(_url_for(pg_url, 'dewpoint_start_check'))}?sslmode=disable",
        "DEWPOINT_TEST_PG_ALLOW": f"{workflow_id} {start_request_id}",
    }
    try:
        done = await asyncio.to_thread(
            subprocess.run, [go, "test", "-count=1", "-json", "-run", "Database", "./internal/startcheck/"],
            cwd=TEMPORAL, env=env, capture_output=True, text=True, timeout=600, check=False,
        )  # fmt: skip
    finally:
        await _login_restored(pg_url)  # the NOLOGIN test restores it; a killed run wouldn't
    outcomes = _outcomes(done.stdout)
    assert done.returncode == 0, (outcomes, done.stderr[-2000:])
    assert outcomes and set(outcomes.values()) == {"pass"}, outcomes  # none skipped, none failed
    assert outcomes.get(ALLOW) == "pass", outcomes
