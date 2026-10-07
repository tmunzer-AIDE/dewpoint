# SPDX-License-Identifier: Apache-2.0
"""Every Temporal call the dispatcher makes carries a deadline (the 2b-4b plan's M1b; the owner's D16): the SDK sets
none of its own, so a call that passes none waits for as long as Temporal doesn't answer, holding its cycle. Each pass
runs against the test server with an item of each kind it takes, every call recorded where the SDK makes it
(`ServiceClient._rpc_call`); the schedule and evidence passes, which the dev server serves, are the M1 probe's. Each
item's calls are counted too, against its pass's most (`calls.CALLS`, the owner's D16 review of checkpoint 3: per-item
call maxima before any budget's numbers): the longest path of each kind is driven here."""

import contextlib
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError

from dewpoint.apps.dispatcher import calls, cancels, dispatch, main, reconcile
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.dispatcher.test_reconcile import aged, starting
from tests.apps.test_admission import KEYS
from tests.core.retention.support import tenant, tree

pytestmark = pytest.mark.usefixtures("development_deployment")
NOWHERE = "deadlines-nowhere"  # no worker polls it


@contextlib.contextmanager
def recorded(client: Client) -> Iterator[list[tuple[str, Any]]]:
    """Each call the SDK makes while recorded: its RPC and the deadline it carried (None: none)."""
    cls = type(client.service_client)
    original = cls._rpc_call
    seen: list[tuple[str, Any]] = []

    async def call(self_: Any, rpc: str, req: Any, resp_type: Any, **kw: Any) -> Any:
        seen.append((rpc, kw.get("timeout")))
        return await original(self_, rpc, req, resp_type, **kw)

    cls._rpc_call = call  # type: ignore[method-assign]
    try:
        yield seen
    finally:
        cls._rpc_call = original  # type: ignore[method-assign]


def without_deadline(seen: list[tuple[str, Any]]) -> list[str]:
    return sorted({rpc for rpc, deadline in seen if deadline is None})


async def test_an_uncertain_start_found_is_described_and_verified_with_deadlines(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    lost = await starting(dispatch_sessionmaker, request, api_settings)
    assert (await dispatch.start(env.client, lost)).kind == "started"
    await aged(owner_sessionmaker, request.id)
    with recorded(env.client) as seen:
        assert await reconcile.reconcile_once(dispatch_sessionmaker, env.client, KEYS, api_settings) == {"started": 1}
    assert {"describe_workflow_execution", "get_workflow_execution_history"} <= {rpc for rpc, _ in seen}
    assert without_deadline(seen) == [] and len(seen) == calls.CALLS["reconcile"]


async def test_an_uncertain_start_absent_and_its_namespace_are_asked_with_deadlines(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    await starting(dispatch_sessionmaker, request, api_settings)
    await aged(owner_sessionmaker, request.id)
    with recorded(env.client) as seen:
        assert await reconcile.reconcile_once(dispatch_sessionmaker, env.client, KEYS, api_settings) == {"absent": 1}
    assert {"describe_workflow_execution", "describe_namespace"} <= {rpc for rpc, _ in seen}
    assert without_deadline(seen) == [] and len(seen) == calls.CALLS["reconcile"]


async def _started(queued: Any, dispatch_sessionmaker: Any, api_settings: Any, client: Client) -> Any:
    _, _, request = queued
    found = await starting(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, await dispatch.start(client, found)) == "started"
    return request


async def test_an_open_run_whose_execution_closed_is_described_with_a_deadline(
    queued, dispatch_sessionmaker, api_settings, env
) -> None:
    request = await _started(queued, dispatch_sessionmaker, api_settings, env.client)
    await env.client.get_workflow_handle(run_workflow_id(str(request.tenant_id), str(request.id))).terminate()
    with recorded(env.client) as seen:
        assert await reconcile.reconcile_once(dispatch_sessionmaker, env.client, KEYS, api_settings) == {"ended": 1}
    assert seen and without_deadline(seen) == [] and len(seen) <= calls.CALLS["reconcile"]


async def test_a_leaked_slot_is_described_with_a_deadline(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    request = await _started(queued, dispatch_sessionmaker, api_settings, env.client)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update runs set status = 'failed', ended_at = now() where id = :i"), {"i": request.id})
    await env.client.get_workflow_handle(run_workflow_id(str(request.tenant_id), str(request.id))).terminate()
    with recorded(env.client) as seen:
        assert await reconcile.reconcile_once(dispatch_sessionmaker, env.client, KEYS, api_settings) == {"released": 1}
    assert seen and without_deadline(seen) == [] and len(seen) <= calls.CALLS["reconcile"]


async def test_a_sub_run_its_roots_close_left_running_is_described_with_a_deadline(
    owner_sessionmaker, dispatch_sessionmaker, env
) -> None:
    ctx = await tenant(owner_sessionmaker)
    orphan = await tree(owner_sessionmaker, ctx, timedelta(minutes=5), request_status=None, sub_ago=None)
    handle = await env.client.start_workflow("Orphan", id=run_workflow_id(str(ctx["t"]), str(orphan["sub"])),
                                             task_queue=NOWHERE)  # fmt: skip
    await handle.terminate()
    with recorded(env.client) as seen:
        assert await reconcile.reconcile_subruns(dispatch_sessionmaker, env.client) == {"ended": 1}
    assert seen and without_deadline(seen) == [] and len(seen) <= calls.CALLS["subruns"]


async def test_a_cancel_is_sent_with_a_deadline(queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env):
    request = await _started(queued, dispatch_sessionmaker, api_settings, env.client)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set cancel_requested_at = now() where id = :i"), {"i": request.id})
    with recorded(env.client) as seen:
        assert sum((await cancels.send_cancels(dispatch_sessionmaker, env.client)).values()) == 1
    assert {"request_cancel_workflow_execution"} <= {rpc for rpc, _ in seen}
    assert without_deadline(seen) == [] and len(seen) <= calls.CALLS["cancels"]


async def test_a_dispatch_start_carries_its_deadline(queued, dispatch_sessionmaker, api_settings, env) -> None:
    _, _, request = queued
    found = await starting(dispatch_sessionmaker, request, api_settings)
    with recorded(env.client) as first:
        await dispatch.start(env.client, found)
    with recorded(env.client) as seen:
        await dispatch.start(env.client, found)  # already started: verified against its history, its longest path
    assert [rpc for rpc, _ in seen] == ["start_workflow_execution", "get_workflow_execution_history"]
    assert without_deadline(first + seen) == [] and len(seen) == calls.CALLS["dispatch"]


async def test_the_current_build_is_asked_with_a_deadline(env) -> None:
    """Every dispatcher asks each cycle (the test server serves no Worker Deployments: what's asked is what counts)."""
    with recorded(env.client) as seen, contextlib.suppress(RPCError):
        await main.current_build(env.client)
    assert seen and without_deadline(seen) == []


async def test_a_completed_runs_result_is_read_with_a_deadline() -> None:
    """The completed path, which no execution reaches here without a worker: its result is read with a deadline."""
    asked: dict[str, Any] = {}

    class Handle:
        async def result(self, **kw: Any) -> Any:
            asked.update(kw)
            return reconcile.RunResult(status="succeeded", iterations=0)

    await reconcile._ended(Handle(), WorkflowExecutionStatus.COMPLETED, uuid.uuid4())
    assert asked.get("rpc_timeout") == reconcile.CALL_DEADLINE


async def test_a_cancel_whose_execution_is_gone_asks_the_namespace_its_second_and_last_call(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    """A cancel's longest path: NOT_FOUND (its execution recorded started but not in Temporal, as one whose history
    retention removed), then whether the namespace answers (`calls.CALLS["cancels"]`)."""
    _, _, request = queued
    found = await starting(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("started")) == "started"
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set cancel_requested_at = now() where id = :i"), {"i": request.id})
    with recorded(env.client) as seen:
        assert await cancels.send_cancels(dispatch_sessionmaker, env.client) == {"closed": 1}
    assert [rpc for rpc, _ in seen] == ["request_cancel_workflow_execution", "describe_namespace"]
    assert without_deadline(seen) == [] and len(seen) == calls.CALLS["cancels"]
