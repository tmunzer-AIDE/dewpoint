# SPDX-License-Identifier: Apache-2.0
"""A step whose outcome no one recorded (the owner's ruling on the 2b-4b M2 checkpoint). When an unexpected bug fails a
run's execution, the rows it hadn't projected yet are absent, and a row persisted `running` is closed `failed` with
`outcome_unconfirmed`: whether the step ran is unconfirmed, and it is never shown as a plugin's failure.

A run whose end is recorded has no step `running`: the end write closes what's left, and a row that arrives later (a
projection of the failed execution, late) lands closed. A batch shares its run's id, so its parent closes only that
batch's own iterations: a sibling's are untouched. Ordinary failures keep their rows as they were projected."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service as runs
from dewpoint.core.runs.service import OUTCOME_UNCONFIRMED
from dewpoint.engine.runtime.activities import CloseBatchInput, ProjectInput, RunSummary, StepRow, UnconfirmedBatch
from tests.core.runs.test_service import seeded_run
from tests.support.keys import FixtureKeys

pytestmark = pytest.mark.usefixtures("development_deployment")
NOW = datetime.now(UTC).isoformat()


def row(run_id: uuid.UUID, step: int, status: str, key: str = "", attempt: int = 1) -> StepRow:
    ended = None if status == "running" else NOW
    return StepRow(str(run_id), str(uuid.UUID(int=step)), f"n{step}", key, attempt, status, ended_at=ended)


async def stored(owner: Any, tenant: uuid.UUID, run_id: uuid.UUID) -> dict[tuple[int, str], tuple[str, str | None]]:
    """Each row as (its step's number, its iteration key): its status and error code."""
    async with owner() as s, s.begin():
        await tenant_scope(s, tenant)
        return {
            (uuid.UUID(str(r.step_id)).int, r.iteration_key): (r.status, r.error_code)
            for r in await runs.run_steps(s, run_id)
        }


def end(run_id: uuid.UUID, **fields: Any) -> RunSummary:
    return RunSummary(str(run_id), fields.pop("status", "failed"), NOW, **fields)


async def test_a_runs_end_leaves_no_step_running(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    """Its end write closes a row still `running` (`outcome_unconfirmed`); every row with an outcome keeps it."""
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    store = DbRunStore(worker_sessionmaker, FixtureKeys())
    await store.project(ProjectInput(str(tenant), [row(run_id, 1, "running"), row(run_id, 2, "succeeded")]))
    await store.project(ProjectInput(str(tenant), [row(run_id, 3, "failed")], end(run_id, error_code="internal_error")))
    assert await stored(owner_sessionmaker, tenant, run_id) == {
        (1, ""): ("failed", OUTCOME_UNCONFIRMED),
        (2, ""): ("succeeded", None),
        (3, ""): ("failed", None),
    }


async def test_a_running_row_arriving_after_its_runs_end_lands_closed(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:  # fmt: skip
    """A projection of a failed execution, late: its `running` rows land closed, a new one or one closed already; a
    recorded outcome (succeeded) still replaces 'unconfirmed', being one."""
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    store = DbRunStore(worker_sessionmaker, FixtureKeys())
    await store.project(ProjectInput(str(tenant), [row(run_id, 1, "running"), row(run_id, 2, "running")]))
    await store.project(ProjectInput(str(tenant), [], end(run_id)))
    await store.project(ProjectInput(str(tenant), [row(run_id, 1, "running"), row(run_id, 2, "succeeded"),
                                                   row(run_id, 4, "running")]))  # fmt: skip
    assert await stored(owner_sessionmaker, tenant, run_id) == {
        (1, ""): ("failed", OUTCOME_UNCONFIRMED),
        (2, ""): ("succeeded", None),
        (4, ""): ("failed", OUTCOME_UNCONFIRMED),
    }


@pytest.mark.parametrize(
    ("key", "inside"),
    [("l:1", True), ("l:1/m:0", True), ("l:2", True), ("l:3", False), ("l:10", False), ("l:0", False), ("", False),
     ("k:1", False), ("l:1x", False), ("ll:1", False)],
)  # fmt: skip
def test_a_batch_holds_its_own_iterations_and_what_they_nest(key: str, inside: bool) -> None:
    """A batch of loop `l`'s items 1 to 3 (excluded), at the run's root: `l:1` and `l:1/m:0` are its, `l:10` (whose key
    begins as `l:1`'s does) is not."""
    assert runs.in_batch(key, UnconfirmedBatch("", "l", 1, 3)) is inside


@pytest.mark.parametrize(("key", "inside"), [("o:3/l:1", True), ("o:4/l:1", False), ("o:3/m:1", False), ("l:1", False)])
def test_a_batch_inside_an_iteration_holds_only_that_iterations_items(key: str, inside: bool) -> None:
    assert runs.in_batch(key, UnconfirmedBatch("o:3", "l", 0, 2)) is inside


ROWS = ["l:1", "l:1/m:0", "l:2", "l:10", "l:0", "k:1", ""]  # the batch below holds the first three


async def test_closing_a_batch_closes_its_iterations_alone(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:  # fmt: skip
    """The batch of `l`'s items 1 and 2: each iteration and everything nested in it is closed; `l:10`, another loop,
    the run's own steps, and a row with an outcome are untouched."""
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    store = DbRunStore(worker_sessionmaker, FixtureKeys())
    rows = [row(run_id, n, "running", key) for n, key in enumerate(ROWS)]
    await store.project(ProjectInput(str(tenant), [*rows, row(run_id, 9, "succeeded", "l:2")]))
    await store.close_batch(closing(tenant, run_id))
    found = await stored(owner_sessionmaker, tenant, run_id)
    assert {k: v for k, v in found.items() if v[0] != "running"} == {
        (0, "l:1"): ("failed", OUTCOME_UNCONFIRMED),
        (1, "l:1/m:0"): ("failed", OUTCOME_UNCONFIRMED),
        (2, "l:2"): ("failed", OUTCOME_UNCONFIRMED),
        (9, "l:2"): ("succeeded", None),
    }
    assert sorted(k for k, v in found.items() if v[0] == "running") == [(3, "l:10"), (4, "l:0"), (5, "k:1"), (6, "")]


def closing(tenant: uuid.UUID, run_id: uuid.UUID) -> CloseBatchInput:
    return CloseBatchInput(str(tenant), str(run_id), UnconfirmedBatch("", "l", 1, 3))


async def test_a_row_late_into_a_closed_batch_lands_closed_while_its_run_still_runs(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:  # fmt: skip
    """The owner's review of the fence: the failed batch's own projection, landing after its parent closed the batch
    while the run (the parent) still runs. The batch's closing is kept on the run's row, which a projection reads under
    the row's lock: a `running` row inside the batch lands closed, a new one or one nested deeper; rows outside it
    (a sibling's, `l:10`, the run's own) land as projected."""
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    store = DbRunStore(worker_sessionmaker, FixtureKeys())
    await store.close_batch(closing(tenant, run_id))
    await store.project(ProjectInput(str(tenant), [row(run_id, n, "running", key) for n, key in enumerate(ROWS)]))
    found = await stored(owner_sessionmaker, tenant, run_id)
    assert {k for k, v in found.items() if v == ("failed", OUTCOME_UNCONFIRMED)} == {(0, "l:1"), (1, "l:1/m:0"),
                                                                                    (2, "l:2")}  # fmt: skip
    assert sorted(k for k, v in found.items() if v[0] == "running") == [(3, "l:10"), (4, "l:0"), (5, "k:1"), (6, "")]
    async with owner_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        assert (await runs.get_run(s, run_id)).status == "running"  # type: ignore[union-attr]


async def test_a_batchs_closing_and_its_late_projection_racing_leave_none_of_its_steps_running(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:  # fmt: skip
    """Whichever commits second sees the other's work (the run's row: the closing holds it for update, a projection
    for share): raced again and again, no step of the batch is left `running`, and none outside it is closed."""
    store = DbRunStore(worker_sessionmaker, FixtureKeys())
    for _ in range(20):
        tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
        late = ProjectInput(str(tenant), [row(run_id, n, "running", key) for n, key in enumerate(ROWS)])
        await asyncio.gather(store.close_batch(closing(tenant, run_id)), store.project(late))
        found = await stored(owner_sessionmaker, tenant, run_id)
        assert sorted(k for k, v in found.items() if v[0] == "running") == [(3, "l:10"), (4, "l:0"), (5, "k:1"),
                                                                           (6, "")]  # fmt: skip
