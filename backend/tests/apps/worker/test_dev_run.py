# SPDX-License-Identifier: Apache-2.0
"""`dev_run_version` (spec §9): the dev CLI's path, through the dispatch role, to a run of the active version."""

from typing import Any

from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.cli.main import dev_run_version
from dewpoint.apps.worker.store import DbRunStore
from tests.apps.test_workflow_ops import actor, create, publish
from tests.apps.worker.harness import workers
from tests.conftest import _url_for
from tests.support.graphs import G, cel, ref
from tests.support.registry import sync_test_plugins


def graph() -> dict[str, Any]:
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        "outputs": {"v": ref("steps.a.output.value")},
    }
    return g.node("a", "testkit.echo@1", {"value": cel("trigger.x + 1")}).data()


async def test_dev_run_starts_the_active_version(
    env: WorkflowEnvironment,
    pg_url: str,
    owner_sessionmaker: Any,
    api_sessionmaker: Any,
    admin_sessionmaker: Any,
    worker_sessionmaker: Any,
    api_settings: Any,
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    out = await publish(api_sessionmaker, ctx, await create(api_sessionmaker, ctx, graph()), api_settings)
    assert out.version is not None
    settings = api_settings.model_copy(update={"database_url": _url_for(pg_url, "dewpoint_dispatch")})
    common: dict[str, Any] = {"tenant_id": ctx.tenant_id, "version_id": out.version.id, "trigger": {"x": 1}}
    async with workers(env.client, DbRunStore(worker_sessionmaker)):
        _, waited = await dev_run_version(settings, env.client, **common)
        _, simulated = await dev_run_version(settings, env.client, simulate=True, **common)
        started, nothing = await dev_run_version(settings, env.client, wait=False, **common)
        await env.client.get_workflow_handle(str(started)).result()
    assert waited is not None and (waited.status, waited.outputs) == ("succeeded", {"v": 2})
    assert simulated is not None and simulated.outputs == {"v": {"simulated": 2}}
    assert nothing is None
