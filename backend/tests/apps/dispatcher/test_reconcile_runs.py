# SPDX-License-Identifier: Apache-2.0
"""Rows left `running` whose workflow closed (engine 2b spec §7.6): the reconciler follows the logical run to its
latest execution and records the end Temporal reports, releasing the slot in the same transaction. This is how a run
whose end write never landed, or was refused after its slot was released (the owner's M2 ruling), still ends."""

import asyncio
import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.client import WorkflowExecutionStatus

from dewpoint.apps.dispatcher import dispatch, reconcile
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.engine.runtime.activities import ProjectInput
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.dispatcher.support import BUILD, begin, state
from tests.apps.test_admission import KEYS
from tests.apps.worker.harness import workers

pytestmark = pytest.mark.usefixtures("development_deployment")


async def started(dispatch_sessionmaker: Any, request: Any, settings: Any, client: Any = None) -> dispatch.Starting:
    """`started`, its slot held and its row `running`: through a real start on `client`, or confirmed without one."""
    found = await begin(dispatch_sessionmaker, request, settings)
    assert isinstance(found, dispatch.Starting)
    outcome = await dispatch.start(client, found) if client is not None else dispatch.Outcome("started")
    assert await dispatch.settle(dispatch_sessionmaker, found, outcome) == "started"
    return found


async def ended(owner: Any, run_id: Any) -> tuple[Any, ...]:
    async with owner() as s:
        row = await s.execute(text("select status, error_code from runs where id = :i"), {"i": run_id})
        return tuple(row.one())


class NoEndWrite(DbRunStore):
    """The worker's projection, but the root's end write never lands (a worker gone between its last step and it)."""

    async def project(self, data: ProjectInput) -> None:
        await super().project(dataclasses.replace(data, run=None))


class Described:
    """A client whose execution has closed with `status`."""

    namespace = "default"

    def __init__(self, status: WorkflowExecutionStatus) -> None:
        self.status = status

    def get_workflow_handle(self, _: str, **__: Any) -> Any:
        status = self.status

        class Handle:
            async def describe(self) -> Any:
                return SimpleNamespace(status=status, close_time=None)

        return Handle()


async def test_a_run_whose_execution_was_terminated_is_recorded_terminated_and_frees_its_slot(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    await started(dispatch_sessionmaker, request, api_settings, env.client)
    await env.client.get_workflow_handle(run_workflow_id(str(request.tenant_id), str(request.id))).terminate()
    assert await reconcile.reconcile_once(dispatch_sessionmaker, env.client, KEYS, api_settings) == {"ended": 1}
    assert await ended(owner_sessionmaker, request.id) == ("failed", "terminated")
    assert (await state(owner_sessionmaker, request.id))["slot"] == 0


@pytest.mark.parametrize("refused", [False, True], ids=["end_write_lost", "end_write_refused"])
async def test_a_completed_run_whose_end_write_never_landed_ends_with_its_own_result(
    queued, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings, env, refused
) -> None:
    ctx, _, request = queued
    async with workers(env.client, NoEndWrite(worker_sessionmaker, KEYS)):
        assert await dispatch.dispatch_once(dispatch_sessionmaker, env.client, KEYS, api_settings, BUILD) == {
            "started": 1
        }
        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(request.id)))
        assert (await asyncio.wait_for(handle.result(), 30)).status == "succeeded"
    assert (await ended(owner_sessionmaker, request.id))[0] == "running"
    if refused:  # the refused end write released its slot already (the owner's ruling on Task 10)
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("delete from run_slots where run_id = :i"), {"i": request.id})
    assert await reconcile.reconcile_once(dispatch_sessionmaker, env.client, KEYS, api_settings) == {"ended": 1}
    assert await ended(owner_sessionmaker, request.id) == ("succeeded", None)
    assert (await state(owner_sessionmaker, request.id))["slot"] == 0


@pytest.mark.parametrize(
    ("status", "recorded"),
    [
        (WorkflowExecutionStatus.CANCELED, ("cancelled", "cancelled")),
        (WorkflowExecutionStatus.FAILED, ("failed", "internal_error")),
        (WorkflowExecutionStatus.TIMED_OUT, ("failed", "internal_error")),
    ],
    ids=["canceled", "failed", "timed_out"],
)
async def test_the_end_temporal_reports_is_recorded(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, status, recorded
) -> None:
    _, _, request = queued
    await started(dispatch_sessionmaker, request, api_settings)
    assert await reconcile.reconcile_once(dispatch_sessionmaker, Described(status), KEYS, api_settings) == {"ended": 1}
    assert await ended(owner_sessionmaker, request.id) == recorded
    assert (await state(owner_sessionmaker, request.id))["slot"] == 0


@pytest.mark.parametrize("status", [WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.CONTINUED_AS_NEW])
async def test_a_live_logical_run_is_left_running(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, status
) -> None:
    """Continued as new: its successor is the logical run's latest execution, still to be followed."""
    _, _, request = queued
    await started(dispatch_sessionmaker, request, api_settings)
    assert await reconcile.reconcile_once(dispatch_sessionmaker, Described(status), KEYS, api_settings) == {
        "running": 1
    }
    assert await ended(owner_sessionmaker, request.id) == ("running", None)
    assert (await state(owner_sessionmaker, request.id))["slot"] == 1
