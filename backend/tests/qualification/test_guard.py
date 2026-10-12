# SPDX-License-Identifier: Apache-2.0
"""Each target-qualification procedure refuses to run without its approval (2b-4b M4 recovery, task 18): before it
reads its arguments, `--help` included, it needs `DEWPOINT_QUALIFICATION_APPROVED=<approval id>`, and exits 2 without
one, having touched nothing. Approved, it still names no target of its own: without the target's arguments it stops at
its usage. Nothing here runs a procedure against anything."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).parents[2]
PROCEDURES = ("admission", "logging", "privileges", "server_verification", "d6", "clock_skew")
APPROVAL = "DEWPOINT_QUALIFICATION_APPROVED"


def _run(procedure: str, *args: str, approval: str | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != APPROVAL and not k.startswith("DEWPOINT_QUALIFICATION_")}
    if approval is not None:
        env[APPROVAL] = approval
    return subprocess.run([sys.executable, "-m", f"tests.qualification.{procedure}", *args], cwd=BACKEND, env=env,
                          capture_output=True, text=True, timeout=60, check=False)  # fmt: skip


@pytest.mark.parametrize("procedure", PROCEDURES)
@pytest.mark.parametrize("approval", [None, "", "   ", "no spaces allowed", "x"])
def test_without_an_approval_each_procedure_refuses_before_anything_else(procedure: str, approval: str | None) -> None:
    run = _run(procedure, "--help", approval=approval)  # its arguments not even read
    assert run.returncode == 2, run.stdout + run.stderr
    assert run.stdout == ""
    assert f"refused: {APPROVAL}=<approval id> is required" in run.stderr


@pytest.mark.parametrize("procedure", PROCEDURES)
def test_approved_it_still_names_no_target_of_its_own(procedure: str) -> None:
    run = _run(procedure, approval="TQ-2026-0001")
    assert run.returncode == 2, run.stdout + run.stderr
    assert "usage:" in run.stderr and "required" in run.stderr


def test_every_procedure_in_the_directory_is_guarded() -> None:
    found = {p.stem for p in Path(__file__).parent.glob("*.py") if not p.stem.startswith("test_")}
    assert found - {"__init__", "approval"} == set(PROCEDURES)
