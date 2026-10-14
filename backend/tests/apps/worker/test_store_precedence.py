# SPDX-License-Identifier: Apache-2.0
"""The worker's store under the upsert precedence (the simulation design §3.4): a step's row projected late, after its
run ended, lands provisional and never replaces the genuine result there before it; a different genuine result for the
same attempt is refused, and logged by ids and statuses only."""

import uuid
from typing import Any

import structlog
from sqlalchemy import text

from dewpoint.apps.worker.store import DbRunStore
from dewpoint.engine.runtime.activities import ProjectInput, StepRow
from tests.apps.test_admission import KEYS
from tests.core.runs.test_service import seeded_run, steps

STEP = str(uuid.UUID(int=7))


def step(run_id: uuid.UUID, status: str, **extra: Any) -> StepRow:
    return StepRow(str(run_id), STEP, "a", "", 1, status, **extra)


async def test_a_running_row_projected_after_its_runs_end_never_replaces_its_result(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    """`_late()` closes a `running` row of an ended run as `outcome_unconfirmed`: that close used to replace the genuine
    result projected before it."""
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    store = DbRunStore(worker_sessionmaker, KEYS)
    done = step(run_id, "succeeded", output_preview={"v": 1}, outcome="applied")
    await store.project(ProjectInput(str(tenant), [done]))
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update runs set status = 'succeeded', ended_at = now() where id = :i"), {"i": run_id})
    await store.project(ProjectInput(str(tenant), [step(run_id, "running")]))
    [only] = await steps(owner_sessionmaker, tenant, run_id)
    assert (only.status, only.output_preview, only.error_code) == ("succeeded", {"v": 1}, None)


async def test_a_different_result_for_the_same_attempt_is_logged_by_ids_and_statuses(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    store = DbRunStore(worker_sessionmaker, KEYS)
    await store.project(ProjectInput(str(tenant), [step(run_id, "succeeded", output_preview={"v": 1})]))
    other = step(run_id, "failed", error_code="boom", error_message="a message, never logged")
    with structlog.testing.capture_logs() as seen:
        await store.project(ProjectInput(str(tenant), [other]))
    [event] = [e for e in seen if e["event"] == "step_result_conflict"]
    assert event == {
        "event": "step_result_conflict",
        "log_level": "warning",
        "run_id": str(run_id),
        "step_id": STEP,
        "iteration_key": "",
        "attempt": 1,
        "kept": "succeeded",
        "refused": "failed",
    }
    [only] = await steps(owner_sessionmaker, tenant, run_id)
    assert (only.status, only.output_preview) == ("succeeded", {"v": 1})
