# SPDX-License-Identifier: Apache-2.0
"""A draft simulation's run (B8; the simulation design §6.4) on the time-skipping server: dispatch starts it from its
snapshot and the worker loads that snapshot, its run row naming it and no version; a step alone runs from its seeds,
the one step instantiated (S2); the reconciler expects the start dispatch sent."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.dispatcher import dispatch, reconcile
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.dispatcher.support import BUILD, begin, workers
from tests.apps.test_admission import KEYS, current
from tests.apps.test_admission_drafts import drafted, simulate
from tests.apps.worker.harness import workers as running
from tests.support.graphs import G, cel, nid, ref

pytestmark = pytest.mark.usefixtures("development_deployment")

TRANSFORMS = (
    G().node("a", "flow.transform@1", {"fields": {"n": cel("1 + 1")}})
    .node("b", "flow.transform@1", {"fields": {"m": ref("steps.a.output.n")}}).edge("a", "b").data()
    | {"settings": {"input_schema": {"type": "object"}}}
)  # fmt: skip


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker) -> Any:
    """A tenant with a draft never published, and the current build's workers ready."""
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, TRANSFORMS)
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    return ctx, wf


async def ran(env: Any, ctx: Any, request: Any, dispatch_sessionmaker: Any, worker_sessionmaker: Any,
              settings: Any) -> Any:  # fmt: skip
    async with running(env.client, DbRunStore(worker_sessionmaker, KEYS)):
        assert await dispatch.dispatch_once(dispatch_sessionmaker, env.client, KEYS, settings, BUILD) == {"started": 1}
        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(request.id)))
        return await asyncio.wait_for(handle.result(), 30)


async def rows(owner: Any, request: Any) -> tuple[Any, list[Any]]:
    async with owner() as s:
        run = (await s.execute(text("select workflow_version_id, draft_snapshot_id, target_step_id, mode, status "
                                    "from runs where id = :i"), {"i": request.id})).one()  # fmt: skip
        steps = (await s.execute(text("select node_key, status, output_preview from run_steps where run_id = :i "
                                      "order by node_key"), {"i": request.id})).all()  # fmt: skip
    return tuple(run), [tuple(r) for r in steps]


async def test_a_draft_simulation_runs_to_its_end_on_its_snapshot(
    ready, env, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings)).request
    result = await ran(env, ctx, request, dispatch_sessionmaker, worker_sessionmaker, api_settings)
    assert result.status == "succeeded", result.error
    run, steps = await rows(owner_sessionmaker, request)
    assert run == (None, request.draft_snapshot_id, None, "simulate", "succeeded")
    assert steps == [("a", "succeeded", {"n": 2}), ("b", "succeeded", {"m": 2})]


async def test_a_step_runs_alone_from_its_snapshot_and_its_seeds(
    ready, env, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
                              values={"/steps/a/output/n": 7})).request  # fmt: skip
    result = await ran(env, ctx, request, dispatch_sessionmaker, worker_sessionmaker, api_settings)
    assert result.status == "succeeded", result.error
    run, steps = await rows(owner_sessionmaker, request)
    assert run == (None, request.draft_snapshot_id, nid("b"), "simulate", "succeeded")
    assert steps == [("b", "succeeded", {"m": 7})]  # `a` was never instantiated


async def test_the_reconciler_expects_the_start_dispatch_sent(
    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
                              values={"/steps/a/output/n": 7})).request  # fmt: skip
    started = await begin(dispatch_sessionmaker, request, api_settings)
    assert isinstance(started, dispatch.Starting)
    sent = started.start
    assert (sent.version_id, sent.target_step_id, sent.mode) == (str(request.draft_snapshot_id), str(nid("b")),
                                                                 "simulate")  # fmt: skip
    expected = await reconcile._expected(dispatch_sessionmaker, KEYS, api_settings, ctx.tenant_id, request.id)
    assert expected is not None and expected.start == sent
