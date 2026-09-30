# SPDX-License-Identifier: Apache-2.0
"""Admission and the deployment's current build (spec §7), on Temporal's dev server with the database. A new run
starts on the deployment's current build, so a version is admitted only when that build runs its engine ABI,
whichever build's process admits it: during a rollout, both builds' processes start runs. The version loader stays
the backstop for a promotion that races a start (test_run_graph_abi.py, test_two_builds.py)."""

import uuid
from typing import Any

import pytest
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.runs import NotAdmissibleError, start_run
from dewpoint.apps.worker.deployment import current_abi, set_current, this_build
from dewpoint.apps.worker.main import engine_worker
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.engine import ENGINE_ABI
from dewpoint.engine.runtime.build import abi_of
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.test_workflow_ops import ECHO_GRAPH, actor, create, publish, published_by_the_previous_build
from tests.apps.worker.test_deployment import placement
from tests.apps.worker.test_main import settings
from tests.engine.replay.record import executions
from tests.support.plugins.testkit import TESTKIT
from tests.support.registry import sync_test_plugins

pytestmark = pytest.mark.usefixtures("development_deployment")  # runs are admitted: engine 2b spec §2.3

OLD, NEW = ENGINE_ABI - 1, ENGINE_ABI  # the build before this one, and this one


def dewpoint_build(abi: int) -> str:
    """A build ID of the test's own that names `abi`, as a Dewpoint build's does."""
    return f"dewpoint-0.0.0.dev{uuid.uuid4().int % 10**9}+abi{abi}"


def test_a_build_id_names_its_abi() -> None:
    assert (abi_of(this_build()), abi_of("dewpoint-0.1.0+abi12")) == (ENGINE_ABI, 12)
    assert [abi_of(b) for b in ("n-1-3f2a", "dewpoint-0.1.0", "other-0.1.0+abi3", "dewpoint-0.1.0+abix")] == [None] * 4


async def test_admission_follows_the_current_build_through_a_promotion(
    dev_env: WorkflowEnvironment,
    owner_sessionmaker: Any,
    api_sessionmaker: Any,
    admin_sessionmaker: Any,
    dispatch_sessionmaker: Any,
    worker_sessionmaker: Any,
    api_settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This process is build N's. Before N is promoted, N-1 is current: N-1's version is admitted and runs on N-1, and
    N's own version is refused. After the promotion it's the other way round: N-1's version is refused, as it would be
    from an N-1 process, and N's runs on N."""
    client = dev_env.client
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    old_wf = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="published by N-1")
    new_wf = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="published by N")
    old = await published_by_the_previous_build(api_sessionmaker, ctx, old_wf, api_settings, monkeypatch)
    new = (await publish(api_sessionmaker, ctx, new_wf, api_settings)).version
    assert new is not None

    async def started(version_id: uuid.UUID) -> uuid.UUID:
        return await start_run(
            dispatch_sessionmaker, client, api_settings, tenant_id=ctx.tenant_id, version_id=version_id, trigger={}
        )

    store = DbRunStore(worker_sessionmaker)
    n1, n = dewpoint_build(OLD), dewpoint_build(NEW)
    async with engine_worker(client, store, [TESTKIT], settings(), build=n1, identity=n1, abi=OLD):
        await set_current(client, n1)
        async with engine_worker(client, store, [TESTKIT], settings(), build=n, identity=n):
            assert await current_abi(client) == OLD
            with pytest.raises(NotAdmissibleError) as early:
                await started(new.id)
            on_old = await started(old.id)
            # it ends before the promotion: a run whose first task hadn't run yet would start on N, and fail as it
            # loads its version (the loader's backstop, for a promotion that races a start)
            results = [await client.get_workflow_handle_for(RunGraph.run, str(on_old)).result()]
            await set_current(client, n)
            assert await current_abi(client) == NEW
            with pytest.raises(NotAdmissibleError) as late:
                await started(old.id)
            on_new = await started(new.id)
            results.append(await client.get_workflow_handle_for(RunGraph.run, str(on_new)).result())
            chains = [await executions(client, str(r), "") for r in (on_old, on_new)]
    assert early.value.reasons == [
        f"This version was published for engine ABI {NEW}, and the current build runs ABI {OLD}: make a build of ABI "
        f"{NEW} current first."
    ]
    assert late.value.reasons == [
        f"This version was published for engine ABI {OLD}, and the current build runs ABI {NEW}: publish the workflow "
        f"again with a build of ABI {NEW}."
    ]
    assert [r.status for r in results] == ["succeeded", "succeeded"]
    assert [placement(chain[0]).builds for chain in chains] == [{n1}, {n}]
