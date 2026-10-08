# SPDX-License-Identifier: Apache-2.0
"""3d-1's proof (plugins-3 D22), end to end: a published workflow triggering, acknowledging and resolving one
PagerDuty alert runs through admission, the dispatcher and RunGraph against a local fake of `events.pagerduty.com`
(vetted, pinned and TLS-checked by the guard; its port 443 redirected in the test's socket layer only):

- every event goes to `/v2/enqueue`, carrying the connection's integration key as `routing_key` (the runtime's,
  never the plugin's) and no authentication header;
- the trigger is keyed by the step's idempotency key: answered 503 once, the engine's retry sends the same
  `dedup_key`, so it joins the alert it opened; acknowledge and resolve name that alert through a ref;
- no step's row holds the key, and each event charged the key's quota scope, keyed by a MAC;
- simulated, nothing is sent."""

import asyncio
import ipaddress
import json
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpcore
import pytest
from sqlalchemy import text
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps import dev_run
from dewpoint.apps.dispatcher.dispatch import dispatch_once
from dewpoint.apps.plugin_loader import sync_installed
from dewpoint.apps.worker.network import DbConnections, Network, worker_types
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.db import tenant_scope
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.plugins.flow import PLUGIN as FLOW
from dewpoint.plugins.pagerduty import PLUGIN as PAGERDUTY
from tests.apps.dispatcher.support import BUILD
from tests.apps.dispatcher.support import workers as ready_workers
from tests.apps.test_admission import KEYS, current
from tests.apps.test_workflow_ops import actor, create, publish
from tests.apps.worker.harness import workers
from tests.support.connections import add_connection
from tests.support.graphs import G, ref
from tests.support.netfakes import Request, Server, guard, tls
from tests.support.netfakes import serve as serve_http

pytestmark = pytest.mark.usefixtures("development_deployment")
HOST = "events.pagerduty.com"
NAMES = (HOST,)
ROUTING_KEY = "R" + "q" * 31


def answer(writer: asyncio.StreamWriter, status: int, body: dict[str, Any]) -> None:
    raw = json.dumps(body).encode()
    writer.write(f"HTTP/1.1 {status} X\r\ncontent-type: application/json\r\ncontent-length: {len(raw)}\r\n\r\n".encode()
                 + raw)  # fmt: skip


@pytest.fixture
async def fake(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Server]:
    """The Events API: the first trigger is answered 503 (no `Retry-After`), every event after it 202."""
    triggers = [0]

    async def events(request: Request, writer: asyncio.StreamWriter) -> None:
        event = json.loads(request.body)
        if (request.headers.get("host"), request.target) != (HOST, "/v2/enqueue"):
            answer(writer, 404, {})
        elif event.get("event_action") == "trigger" and triggers[0] == 0:
            triggers[0] += 1
            answer(writer, 503, {"status": "unavailable"})
        else:
            answer(writer, 202, {"status": "success", "message": "Event processed", "dedup_key": event["dedup_key"]})
        await writer.drain()

    async with serve_http(events, tls_names=NAMES) as server:
        connect_tcp = httpcore.AnyIOBackend.connect_tcp

        async def redirected(self: Any, host: str, port: int, *args: Any, **kwargs: Any) -> Any:
            return await connect_tcp(self, host, server.port if (host, port) == ("127.0.0.1", 443) else port, *args,
                                     **kwargs)  # fmt: skip

        monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", redirected)
        yield server


async def _published(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any) -> tuple[Any, uuid.UUID]:
    async with admin() as s, s.begin():
        await sync_installed(s, [FLOW, PAGERDUTY])
    ctx = await actor(owner)
    cid = str(await add_connection(owner, ctx.tenant_id, type_key="pagerduty", config={"region": "us"},
                                   secret={"routing_key": ROUTING_KEY}))  # fmt: skip
    g = G()
    g.node("trigger", "pagerduty.trigger_alert@1", {"connection": cid, "title": "db-1 disk full", "text": "2% free",
                                                     "severity": "critical", "source": "db-1.example.com"})  # fmt: skip
    alert = {"connection": cid, "dedup_key": ref("steps.trigger.output.dedup_key")}
    g.node("ack", "pagerduty.acknowledge_alert@1", alert)
    g.node("resolve", "pagerduty.resolve_alert@1", alert)
    g.edge("trigger", "ack")
    g.edge("ack", "resolve")
    wf = await create(api, ctx, g.data())
    published = await publish(api, ctx, wf, settings)
    assert published.version is not None, published
    await current(dispatch)
    await ready_workers(owner)
    return ctx, wf


async def _run(env: Any, ctx: Any, wf: Any, dispatch: Any, worker: Any, settings: Any, *, simulate: bool) -> Any:
    loopback = AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, ctx.tenant_id)
    network = Network(
        guard=guard({HOST: ["127.0.0.1"]}, [loopback]), connections=DbConnections(worker), sessionmaker=worker,
        keys=KEYS, ssl_context=tls(NAMES).client_context(), types=worker_types([PAGERDUTY]),
    )  # fmt: skip
    request = await dev_run.admit(dispatch, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, input={},
                                  simulate=simulate, idempotency_key=f"pd-{simulate}")  # fmt: skip
    async with workers(env.client, DbRunStore(worker, KEYS), plugins=(PAGERDUTY,), network=network):
        assert await dispatch_once(dispatch, env.client, KEYS, settings, BUILD) == {"started": 1}
        return request, await dev_run.wait_for_end(dispatch, ctx.tenant_id, request.id, within=90, poll=0.1)


async def test_an_alert_is_triggered_once_however_retried_then_acknowledged_and_resolved(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, fake,
) -> None:  # fmt: skip
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings)  # fmt: skip
    _, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=False)
    assert ended == dev_run.Ended("run", "succeeded", None, None), ended
    events = [json.loads(r.body) for r in fake.requests]
    assert [e["event_action"] for e in events] == ["trigger", "trigger", "acknowledge", "resolve"]
    assert all(e["routing_key"] == ROUTING_KEY for e in events)
    assert all("authorization" not in r.headers for r in fake.requests)
    keys = {e["dedup_key"] for e in events}
    assert len(keys) == 1 and re.fullmatch(r"[0-9a-f]{64}", keys.pop())  # the retry and the alert's actions: one key
    assert events[0]["payload"] == {"summary": "db-1 disk full", "source": "db-1.example.com", "severity": "critical",
                                    "custom_details": {"text": "2% free"}}  # fmt: skip
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        rows = (await s.execute(text("select node_key, output_preview::text, input_preview::text, status "
                                     "from run_steps"))).all()  # fmt: skip
        scopes = [k for (k,) in (await s.execute(text("select scope from rate_buckets"))).all()]
    assert sorted((r[0], r[3]) for r in rows) == [
        ("ack", "succeeded"),
        ("resolve", "succeeded"),
        ("trigger", "failed"),
        ("trigger", "succeeded"),
    ]  # a row an attempt
    assert all(ROUTING_KEY not in (r[1] or "") + (r[2] or "") for r in rows)
    assert [k.split(":", 1)[0] for k in scopes] == ["pagerduty.integration"] and ROUTING_KEY not in scopes[0]


async def test_a_simulated_alert_workflow_sends_nothing(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, fake,
) -> None:  # fmt: skip
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings)  # fmt: skip
    _, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=True)
    assert ended is not None and ended.status == "succeeded", ended
    assert fake.requests == []
