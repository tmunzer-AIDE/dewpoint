# SPDX-License-Identifier: Apache-2.0
"""The first slice's proof (plugins-3a-1): a published workflow whose step names a connection runs through admission,
the dispatcher and RunGraph, and its node reaches a local TLS server through the guarded network with the credentials
the runtime applied; a step whose connection points at a private address is refused before anything leaves."""

import ipaddress
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps import dev_run
from dewpoint.apps.dispatcher.dispatch import dispatch_once
from dewpoint.apps.worker.network import DbConnections, Network
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.db import tenant_scope
from dewpoint.core.egress.addresses import AllowEntry
from tests.apps.dispatcher.support import BUILD
from tests.apps.dispatcher.support import workers as ready_workers
from tests.apps.test_admission import KEYS, current
from tests.apps.test_workflow_ops import actor, create, publish
from tests.apps.worker.harness import workers
from tests.support.connections import add_connection, types_for_testkit
from tests.support.graphs import G, ref
from tests.support.netfakes import guard, respond, serve, tls
from tests.support.registry import sync_test_plugins

pytestmark = pytest.mark.usefixtures("development_deployment")
NAMES = ("dewpoint.test",)


async def _published(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any, base_url: str) -> Any:
    await sync_test_plugins(admin)
    ctx = await actor(owner)
    cid = await add_connection(owner, ctx.tenant_id, config={"base_url": base_url})
    g = G()
    g.settings = {"outputs": {"status": ref("steps.call.output.status")}}
    graph = g.node("call", "testkit.http_call@1", {"connection": str(cid), "path": "/hello"}).data()
    wf = await create(api, ctx, graph)
    published = await publish(api, ctx, wf, settings)
    assert published.version is not None and published.version.connection_ids == [cid]
    await current(dispatch)
    await ready_workers(owner)
    return ctx, wf


def _network(worker: Any, tenant: uuid.UUID) -> Network:
    return Network(
        guard=guard(
            {"dewpoint.test": ["127.0.0.1"], "private.test": ["10.0.0.9"]},
            [AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, tenant)],
        ),  # fmt: skip
        connections=DbConnections(worker),
        sessionmaker=worker,
        keys=KEYS,
        ssl_context=tls(NAMES).client_context(),
        types=types_for_testkit(),
    )


async def _run(env: Any, ctx: Any, wf: Any, dispatch: Any, worker: Any, settings: Any, key: str) -> Any:
    request = await dev_run.admit(dispatch, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, input={},
                                  simulate=False, idempotency_key=key)  # fmt: skip
    async with workers(env.client, DbRunStore(worker, KEYS), network=_network(worker, ctx.tenant_id)):
        assert await dispatch_once(dispatch, env.client, KEYS, settings, BUILD) == {"started": 1}
        return request, await dev_run.wait_for_end(dispatch, ctx.tenant_id, request.id, within=30, poll=0.1)


async def test_a_run_reaches_its_connection_through_the_guarded_network(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings,
) -> None:  # fmt: skip
    async with serve(respond(200, b"hello"), tls_names=NAMES) as server:
        ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                                   api_settings, f"https://dewpoint.test:{server.port}")  # fmt: skip
        request, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, "n1")
    assert ended == dev_run.Ended("run", "succeeded", None, None)
    assert [r.headers["authorization"] for r in server.requests] == ["Bearer s3cr3t-token-value"]
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        previews = (await s.execute(text("select output_preview::text from run_steps"))).scalars().all()
    assert previews and all("s3cr3t" not in (p or "") for p in previews)
    index = await DbRunStore(worker_sessionmaker, KEYS).index(str(ctx.tenant_id), str(request.id))
    assert "s3cr3t-token-value" in index.strings


async def test_a_step_whose_connection_points_inward_is_refused(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings,
) -> None:  # fmt: skip
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings, "https://private.test:8443")  # fmt: skip
    _, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, "n2")
    assert ended is not None and ended.status == "failed"
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        codes = (await s.execute(text("select error_code from run_steps where error_code is not null"))).scalars().all()
    assert codes == ["egress_refused"]
