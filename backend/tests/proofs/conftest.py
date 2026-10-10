# SPDX-License-Identifier: Apache-2.0
"""The proofs (2b-4b M4) are opt-in: `DEWPOINT_PROOF` names the ones to run (`d6`, `d12`, `pv`, `sc`,
comma-separated), and only the owner's approval of a run sets it. With `DEWPOINT_PROOF_OUT=<file>`, each case's outcome
is recorded there as JSON lines, beside the environment's own record (images, versions, inventory), for the proof
record."""

import json
import os
from pathlib import Path

import pytest


def enabled(proof: str) -> bool:
    return proof in {p.strip() for p in os.environ.get("DEWPOINT_PROOF", "").split(",")}


def gate(proof: str) -> pytest.MarkDecorator:
    return pytest.mark.skipif(not enabled(proof), reason=f"a proof, run only when authorized (DEWPOINT_PROOF={proof})")


def record(line: dict[str, object]) -> None:
    out = os.environ.get("DEWPOINT_PROOF_OUT")
    if out:
        with Path(out).open("a") as f:
            f.write(json.dumps(line, sort_keys=True, default=str) + "\n")


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Each case's call; its setup when it didn't pass (a skip, a failure); its teardown when it failed (the review's
    I3: a failed cleanup is part of the record)."""
    if (
        report.when == "call"
        or (report.when in ("setup", "teardown") and report.outcome == "failed")
        or (report.when == "setup" and report.outcome == "skipped")
    ):
        if "/proofs/d6/" in report.nodeid or "/proofs/d12/" in report.nodeid:
            record(
                {
                    "case": report.nodeid,
                    "phase": report.when,
                    "outcome": report.outcome,
                    "seconds": round(report.duration, 2),
                }
            )
