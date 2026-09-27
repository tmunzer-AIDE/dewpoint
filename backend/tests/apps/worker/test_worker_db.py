# SPDX-License-Identifier: Apache-2.0
"""A run end to end (spec §8, §9): admitted by `start_run`, executed by `RunGraph`, projected by the worker into
`runs` and `run_steps` under RLS, and read back through the runs API."""

import uuid
from datetime import UTC, datetime
from typing import Any

from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.runs import start_run
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service as runs
from dewpoint.engine.runtime.activities import ProjectInput, RunSummary, StepRow
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.api.helpers import member_client
from tests.apps.test_workflow_ops import actor, create, publish
from tests.apps.worker.harness import workers
from tests.core.runs.test_service import seeded_run
from tests.support.graphs import G, cel, ref
from tests.support.registry import sync_test_plugins


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
    async with workers(env.client, DbRunStore(worker_sessionmaker)):
        run_id = await start_run(
            dispatch_sessionmaker, env.client, api_settings,
            tenant_id=ctx.tenant_id, version_id=out.version.id, trigger={"x": 1},
        )  # fmt: skip
        result = await env.client.get_workflow_handle_for(RunGraph.run, str(run_id)).result()
    assert (result.status, result.outputs) == ("succeeded", {"items": [10, 20]})

    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
    listed = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")).json()
    assert [(r["id"], r["status"], r["iterations"]) for r in listed] == [(str(run_id), "succeeded", 2)]
    detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}")).json()
    steps = {(s["key"], s["iteration_key"]): s for s in detail["steps"]}
    assert steps[("a", "")]["output"] == {"value": 2} and steps[("a", "")]["cel_mode"] == "activity"
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
    await DbRunStore(worker_sessionmaker).project(
        ProjectInput(str(tenant), [attempt(1, "failed"), attempt(2, "bogus"), attempt(3, "succeeded")], summary)
    )
    async with owner_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        stored = [(r.attempt, r.status) for r in await runs.run_steps(s, run_id)]
        run = await runs.get_run(s, run_id)
    assert stored == [(1, "failed"), (3, "succeeded")]
    assert run is not None and (run.status, run.iterations) == ("succeeded", 2)
