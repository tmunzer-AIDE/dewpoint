# SPDX-License-Identifier: Apache-2.0
"""A sub-run left `running` after its root ended (the final review's M5): it held its tree past retention, failed a key
retirement's `open_runs` check and an erasure's stage 50. The reconciler describes the sub-run's own execution, once
its root has been ended for longer than its grace. Closed: the end Temporal reports is recorded. Still live (a child
its root's close asked to cancel, still cancelling): left running. Its history gone: an alert, never an end (the
owner's ruling on missing history). Each is asked about at most once per RECHECK, so more than a pass takes are all
reached."""

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCStatusCode

from dewpoint.apps.dispatcher import reconcile
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.dispatcher.test_reconcile import DescribeFails
from tests.apps.dispatcher.test_reconcile_runs import Described, ended
from tests.apps.test_runs import rpc
from tests.core.retention.support import run, tenant, tree

ENDED_AGO = timedelta(minutes=5)  # past the reconciler's grace


async def _orphan(owner: Any, *, root_ago: timedelta | None = ENDED_AGO) -> dict[str, Any]:
    """A root that ended `root_ago` (None: still running, from before admission) and its sub-run still `running`."""
    ctx = await tenant(owner)
    return {**await tree(owner, ctx, root_ago, request_status=None, sub_ago=None), "ctx": ctx}


@pytest.mark.parametrize(
    ("status", "recorded"),
    [
        (WorkflowExecutionStatus.TERMINATED, ("failed", "terminated")),
        (WorkflowExecutionStatus.CANCELED, ("cancelled", "cancelled")),
        (WorkflowExecutionStatus.TIMED_OUT, ("failed", "internal_error")),
    ],
    ids=["terminated", "canceled", "timed_out"],
)
async def test_a_sub_run_left_running_after_its_root_ended_gets_the_end_temporal_reports(
    owner_sessionmaker, dispatch_sessionmaker, status, recorded
) -> None:
    orphan = await _orphan(owner_sessionmaker)
    assert await reconcile.reconcile_subruns(dispatch_sessionmaker, Described(status)) == {"ended": 1}
    assert await ended(owner_sessionmaker, orphan["sub"]) == recorded


@pytest.mark.parametrize("status", [WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.CONTINUED_AS_NEW])
async def test_a_sub_run_still_live_after_its_root_ended_is_left_running(
    owner_sessionmaker, dispatch_sessionmaker, status
) -> None:
    orphan = await _orphan(owner_sessionmaker)
    assert await reconcile.reconcile_subruns(dispatch_sessionmaker, Described(status)) == {"running": 1}
    assert await ended(owner_sessionmaker, orphan["sub"]) == ("running", None)


async def test_a_sub_run_whose_history_is_gone_is_left_running_with_an_alert(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    orphan = await _orphan(owner_sessionmaker)
    gone = DescribeFails(rpc(RPCStatusCode.NOT_FOUND))
    with structlog.testing.capture_logs() as seen:
        assert await reconcile.reconcile_subruns(dispatch_sessionmaker, gone) == {"unresolved": 1}
    assert await ended(owner_sessionmaker, orphan["sub"]) == ("running", None)
    assert any(e["event"] == "subrun_history_missing" and e["log_level"] == "error" for e in seen)


async def test_a_sub_run_whose_root_runs_or_just_ended_is_left_to_its_parent(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """Its parent writes its end; a root's own end write may land just before its children's."""
    running = await _orphan(owner_sessionmaker, root_ago=None)
    just = await _orphan(owner_sessionmaker, root_ago=timedelta(seconds=1))
    closed = Described(WorkflowExecutionStatus.TERMINATED)
    assert await reconcile.reconcile_subruns(dispatch_sessionmaker, closed) == {}
    for orphan in (running, just):
        assert await ended(owner_sessionmaker, orphan["sub"]) == ("running", None)


class Live:
    """A client whose every execution is still running, recording which ones it was asked about."""

    namespace = "default"

    def __init__(self) -> None:
        self.asked: list[str] = []

    def get_workflow_handle(self, workflow_id: str, **__: Any) -> Any:
        self.asked.append(workflow_id)

        class Handle:
            async def describe(self) -> Any:
                return SimpleNamespace(status=WorkflowExecutionStatus.RUNNING, close_time=None)

        return Handle()


async def test_more_live_sub_runs_than_a_pass_takes_are_all_asked_about(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    orphan = await _orphan(owner_sessionmaker)
    subs = [orphan["sub"], *[await run(owner_sessionmaker, orphan["ctx"], None, parent=orphan["root"])
                             for _ in range(reconcile.BATCH + 9)]]  # fmt: skip
    client = Live()
    passes = [await reconcile.reconcile_subruns(dispatch_sessionmaker, client) for _ in range(2)]
    assert passes == [{"running": reconcile.BATCH}, {"running": 10}]
    assert set(client.asked) == {run_workflow_id(str(orphan["ctx"]["t"]), str(sub)) for sub in subs}
