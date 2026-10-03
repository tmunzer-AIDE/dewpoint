# SPDX-License-Identifier: Apache-2.0
"""A run end to end (spec §8, §9): admitted by `start_run`, executed by `RunGraph`, projected by the worker into
`runs` and `run_steps` under RLS, and read back through the runs API."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.runs import start_run
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service as runs
from dewpoint.engine.runtime.activities import ProjectInput, RunStart, RunSummary, StepRow
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.api.helpers import member_client
from tests.apps.test_workflow_ops import actor, create, publish
from tests.apps.worker.harness import workers
from tests.core.runs.test_service import seeded_run
from tests.support.graphs import G, cel, ref
from tests.support.keys import FixtureKeys
from tests.support.registry import sync_test_plugins

# its runs start on the time-skipping server, in a development deployment (engine 2b spec §2.3)
pytestmark = pytest.mark.usefixtures("this_build_is_current", "development_deployment")


def graph() -> dict[str, Any]:
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        "outputs": {"items": ref("steps.l.output.items")},
    }
    g.node("a", "testkit.echo@1", {"value": cel("trigger.x + 1")})
    g.node("l", "flow.loop@1", {"items": [1, 2], "collect": cel("item * 10")}).node("x", "testkit.echo@1")
    g.node("s", "testkit.sensitive@1")
    g.edge("a", "l").edge("l", "x", "body").edge("l", "s", "done")
    return g.data()


async def test_a_run_is_projected_and_readable_through_the_api(
    env: WorkflowEnvironment,
    owner_sessionmaker: Any,
    api_sessionmaker: Any,
    admin_sessionmaker: Any,
    dispatch_sessionmaker: Any,
    worker_sessionmaker: Any,
    api_settings: Any,
    app: Any,
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    out = await publish(api_sessionmaker, ctx, await create(api_sessionmaker, ctx, graph()), api_settings)
    assert out.version is not None
    async with workers(env.client, DbRunStore(worker_sessionmaker, FixtureKeys())):
        run_id = await start_run(
            dispatch_sessionmaker, env.client, api_settings,
            tenant_id=ctx.tenant_id, version_id=out.version.id, trigger={"x": 1},
        )  # fmt: skip
        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(run_id)))
        result = await handle.result()
    assert (result.status, result.outputs) == ("succeeded", {"items": [10, 20]})

    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
    listed = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")).json()
    assert [(r["id"], r["status"], r["iterations"]) for r in listed] == [(str(run_id), "succeeded", 2)]
    detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}")).json()
    steps = {(s["key"], s["iteration_key"]): s for s in detail["steps"]}
    assert steps[("a", "")]["output"] == {"value": 2} and steps[("a", "")]["cel_mode"] == "local"
    assert steps[("a", "")]["outcome"] == "applied"
    assert {k for k in steps if k[0] == "x"} == {("x", "l:0"), ("x", "l:1")}
    assert steps[("l", "")]["output"] == {"items": [10, 20], "failures": [], "count": 2}
    assert steps[("s", "")]["output"] == {
        "public": "visible",
        "secret_value": "[redacted]",
        "login": {"user": "ops", "password": "[redacted]"},
    }

    other = await actor(owner_sessionmaker)
    stranger, _ = await member_client(app, owner_sessionmaker, api_settings, other.tenant_id, "viewer")
    assert (await stranger.get(f"/api/v1/t/{other.tenant_id}/runs")).json() == []
    assert (await stranger.get(f"/api/v1/t/{other.tenant_id}/runs/{run_id}")).status_code == 404
    assert (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{uuid.uuid4()}")).status_code == 404


async def test_a_row_the_database_refuses_never_holds_up_the_others_or_the_run(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    """Final review: a projection the database refuses (a deterministic error, SQLSTATE class 22 or 23) was retried
    forever: no later row landed, and the run never ended. Each row is then written alone, and one refused again is
    logged and skipped."""
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    step = str(uuid.UUID(int=7))

    def attempt(n: int, status: str) -> StepRow:
        return StepRow(str(run_id), step, "a", "", n, status, ended_at=datetime.now(UTC).isoformat())

    summary = RunSummary(str(run_id), "succeeded", datetime.now(UTC).isoformat(), iterations=2)
    await DbRunStore(worker_sessionmaker, FixtureKeys()).project(
        ProjectInput(str(tenant), [attempt(1, "failed"), attempt(2, "bogus"), attempt(3, "succeeded")], summary)
    )
    async with owner_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        stored = [(r.attempt, r.status) for r in await runs.run_steps(s, run_id)]
        run = await runs.get_run(s, run_id)
    assert stored == [(1, "failed"), (3, "succeeded")]
    assert run is not None and (run.status, run.iterations) == ("succeeded", 2)


async def test_a_character_the_database_refuses_never_keeps_its_run_open(
    env: WorkflowEnvironment,
    owner_sessionmaker: Any,
    api_sessionmaker: Any,
    admin_sessionmaker: Any,
    dispatch_sessionmaker: Any,
    worker_sessionmaker: Any,
    api_settings: Any,
) -> None:
    """PR #9 review: rows were sized as strict UTF-8 in workflow code, before storage replaced what Postgres refuses.
    A `fail` node's message read from a trigger with a lone surrogate raised there: the workflow task failed on every
    retry, no row or summary landed, and the run stayed `running`."""
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    g = G()
    g.settings = {"input_schema": {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}}
    g.node("f", "flow.fail@1", {"message": ref("trigger.note")})
    out = await publish(api_sessionmaker, ctx, await create(api_sessionmaker, ctx, g.data()), api_settings)
    assert out.version is not None
    async with workers(env.client, DbRunStore(worker_sessionmaker, FixtureKeys())):
        run_id = await start_run(
            dispatch_sessionmaker, env.client, api_settings,
            tenant_id=ctx.tenant_id, version_id=out.version.id, trigger={"note": "bad \ud800 note"},
        )  # fmt: skip
        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(run_id)))
        result = await asyncio.wait_for(handle.result(), 30)
    assert result.status == "failed" and result.error is not None
    assert (result.error["code"], result.error["message"]) == ("workflow_failed", "bad \ufffd note")
    async with owner_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        run = await runs.get_run(s, run_id)
        steps = await runs.run_steps(s, run_id)
    assert run is not None
    assert (run.status, run.error_code, run.error_message) == ("failed", "workflow_failed", "bad \ufffd note")
    assert [r.node_key for r in steps] == ["f"]


async def test_a_sub_run_row_the_database_refuses_never_holds_up_its_projection(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    """2a-3b's final review, M5: a sub-run's row the database refuses (here its parent doesn't exist) was retried
    forever, and the sub-run couldn't even be cancelled: its first write is shielded. It's logged and skipped, as a
    refused step row is."""
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        seeded = await runs.get_run(s, run_id)
    assert seeded is not None
    child = uuid.uuid4()
    start = RunStart(
        run_id=str(child),
        workflow_id=str(seeded.workflow_id),
        version_id=str(seeded.workflow_version_id),
        mode="live",
        parent_run_id=str(uuid.uuid4()),  # no such run
        parent_step_id=None,
        parent_iteration_key="",
        kind="subflow",
        started_at=datetime.now(UTC).isoformat(),
    )
    await DbRunStore(worker_sessionmaker, FixtureKeys()).project(ProjectInput(str(tenant), [], None, start))
    async with owner_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        assert await runs.get_run(s, child) is None


async def test_a_sub_flow_is_projected_as_a_run_of_its_own(
    env: WorkflowEnvironment,
    owner_sessionmaker: Any,
    api_sessionmaker: Any,
    admin_sessionmaker: Any,
    dispatch_sessionmaker: Any,
    worker_sessionmaker: Any,
    api_settings: Any,
    app: Any,
) -> None:
    """2a-3b: a sub-flow writes its own `runs` row (as the worker role, with its first projection) before any of its
    steps, pointing at the run and step that started it. The list shows top-level runs; a run shows its children."""
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    sub = G()
    sub.settings = {
        "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
        "outputs": {"double": ref("steps.t.output.double")},
    }
    sub.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.n * 2")}})
    sub_id = await create(api_sessionmaker, ctx, sub.data(), name="doubler")
    assert (await publish(api_sessionmaker, ctx, sub_id, api_settings)).version is not None
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": {"double": ref("steps.r.output.double")}}
    g.node("r", "flow.run_workflow@1", {"workflow_id": str(sub_id), "input": {"n": 21}})
    out = await publish(api_sessionmaker, ctx, await create(api_sessionmaker, ctx, g.data()), api_settings)
    assert out.version is not None
    async with workers(env.client, DbRunStore(worker_sessionmaker, FixtureKeys())):
        run_id = await start_run(
            dispatch_sessionmaker, env.client, api_settings,
            tenant_id=ctx.tenant_id, version_id=out.version.id, trigger={},
        )  # fmt: skip
        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(run_id)))
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"double": 42})
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
    listed = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")).json()
    assert [r["id"] for r in listed] == [str(run_id)]  # the sub-run isn't listed on its own
    detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}")).json()
    [child] = detail["children"]
    step = next(n["id"] for n in g.nodes if n["key"] == "r")
    assert (child["kind"], child["parent_run_id"], child["parent_step_id"], child["status"]) == (
        "subflow",
        str(run_id),
        step,
        "succeeded",
    )
    assert child["workflow_id"] == str(sub_id)
    sub_detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{child['id']}")).json()
    assert [s["key"] for s in sub_detail["steps"]] == ["t"] and sub_detail["parent_run_id"] == str(run_id)


async def test_the_worker_loads_a_versions_pinned_cap_and_depth(
    owner_sessionmaker: Any, api_sessionmaker: Any, admin_sessionmaker: Any, api_settings: Any, worker_sessionmaker: Any
) -> None:
    """Engine 2b spec §5.3: what publish pinned is what a run schedules with."""
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    g = G().node("o", "flow.loop@1", {"items": [1]}).node("e", "testkit.echo@1", {"value": 1}).edge("o", "e", "body")
    out = await publish(api_sessionmaker, ctx, await create(api_sessionmaker, ctx, g.data()), api_settings)
    assert out.version is not None
    data = await DbRunStore(worker_sessionmaker, FixtureKeys()).version(str(ctx.tenant_id), str(out.version.id))
    assert (data.open_scopes_cap, data.loop_depth) == (100, 1)
