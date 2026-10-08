# SPDX-License-Identifier: Apache-2.0
"""3d-2's proof (plugins-3 D22), end to end: a published workflow creating, noting and resolving one ServiceNow
incident runs through admission, the dispatcher and RunGraph against a local fake of an instance's Table API
(`acme.service-now.com`, vetted, pinned and TLS-checked by the guard; its port 443 redirected in the test's socket
layer only):

- every request carries the connection's key as `x-sn-apikey` (the runtime's, never the plugin's) and no
  `authorization` header;
- the create's first attempt stores the incident, then the connection drops before any answer: the engine's retry
  first asks for the step's `correlation_id` (`reconcile()`), finds the incident and creates none (its first wait cut
  from 60 s to 1 s here: the unit tests pin the schedule);
- the note and the resolve name that incident through a ref; the resolve's state is checked;
- a create answered 201 with a body too deep to decode, its incident hidden from the key's user's searches, fails
  `servicenow.created_unreadable` without a retry: one incident (the owner's review of 1eafe63);
- no step's row holds the key, and each request charged the key's quota scope, keyed by a MAC;
- simulated, nothing is sent."""

import asyncio
import ipaddress
import json
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

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
from dewpoint.plugins.servicenow import PLUGIN as SERVICENOW
from dewpoint.plugins.servicenow import CreateIncident
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
HOST = "acme.service-now.com"
NAMES = (HOST,)
API_KEY = "S" + "n" * 39
TABLE = "/api/now/v2/table/incident"


def answer(writer: asyncio.StreamWriter, status: int, body: dict[str, Any]) -> None:
    raw = json.dumps(body).encode()
    writer.write(f"HTTP/1.1 {status} X\r\ncontent-type: application/json\r\ncontent-length: {len(raw)}\r\n\r\n".encode()
                 + raw)  # fmt: skip


DEEP = b"[" * 20_000 + b"]" * 20_000  # json.loads raises RecursionError on it


class Instance:
    """The Table API's incidents: the first create is stored, then its connection drops before any answer. Or, `deep`:
    each create is stored and answered 201 with a body too deep to decode, and a search sees nothing (a read
    restriction on the key's user)."""

    def __init__(self, *, deep: bool = False) -> None:
        self.incidents: dict[str, dict[str, Any]] = {}
        self.notes: list[str] = []
        self.deep = deep

    async def handle(self, request: Request, writer: asyncio.StreamWriter) -> None:
        url = urlsplit(request.target)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if request.headers.get("host") != HOST or not url.path.startswith(TABLE):
            answer(writer, 404, {})
        elif request.method == "POST" and url.path == TABLE:
            number = f"INC{len(self.incidents) + 1:07}"
            record = {**json.loads(request.body), "sys_id": uuid.uuid4().hex, "number": number, "state": "1"}
            self.incidents[record["sys_id"]] = record
            if self.deep:
                writer.write(b"HTTP/1.1 201 X\r\ncontent-type: application/json\r\ncontent-length: %d\r\n\r\n%s"
                             % (len(DEEP), DEEP))  # fmt: skip
            elif len(self.incidents) == 1:
                writer.close()  # stored, and the answer lost
                return
            else:
                answer(writer, 201, {"result": record})
        elif request.method == "GET" and url.path == TABLE and self.deep:
            answer(writer, 200, {"result": []})
        elif request.method == "GET" and url.path == TABLE:
            wanted = query["sysparm_query"].split("^", 1)[0].removeprefix("correlation_id=")
            answer(writer, 200, {"result": [r for r in self.incidents.values() if r.get("correlation_id") == wanted]})
        elif request.method == "PATCH" and url.path.removeprefix(TABLE + "/") in self.incidents:
            record = self.incidents[url.path.removeprefix(TABLE + "/")]
            change = json.loads(request.body)
            if "work_notes" in change:
                self.notes.append(change.pop("work_notes"))
            record.update(change)
            answer(writer, 200, {"result": record})
        else:
            answer(writer, 404, {})
        await writer.drain()


@pytest.fixture(autouse=True)
def quick_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The create's retry waits 1 s, not 60 s, in the manifest this test syncs (a local server doesn't skip time)."""
    monkeypatch.setattr(CreateIncident, "retry", replace(CreateIncident.retry, initial_interval=timedelta(seconds=1)))


@asynccontextmanager
async def serving(monkeypatch: pytest.MonkeyPatch, instance: Instance) -> AsyncIterator[tuple[Server, Instance]]:
    async with serve_http(instance.handle, tls_names=NAMES) as server:
        connect_tcp = httpcore.AnyIOBackend.connect_tcp

        async def redirected(self: Any, host: str, port: int, *args: Any, **kwargs: Any) -> Any:
            return await connect_tcp(self, host, server.port if (host, port) == ("127.0.0.1", 443) else port, *args,
                                     **kwargs)  # fmt: skip

        monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", redirected)
        yield server, instance


@pytest.fixture
async def fake(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[Server, Instance]]:
    async with serving(monkeypatch, Instance()) as served:
        yield served


@pytest.fixture
async def hidden(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[Server, Instance]]:
    async with serving(monkeypatch, Instance(deep=True)) as served:
        yield served


async def _published(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any) -> tuple[Any, uuid.UUID]:
    async with admin() as s, s.begin():
        await sync_installed(s, [FLOW, SERVICENOW])
    ctx = await actor(owner)
    instance = {"instance_url": f"https://{HOST}"}
    cid = str(await add_connection(owner, ctx.tenant_id, type_key="servicenow", config=instance,
                                   secret={"api_key": API_KEY}))  # fmt: skip
    g = G()
    g.node("create", "servicenow.create_incident@1", {"connection": cid, "title": "db-1 disk full",
                                                       "text": "2% free", "severity": "critical"})  # fmt: skip
    incident = {"connection": cid, "sys_id": ref("steps.create.output.sys_id")}
    g.node("note", "servicenow.add_work_note@1", {**incident, "text": "Cleaning /var/log."})
    g.node("resolve", "servicenow.resolve_incident@1", {**incident, "close_code": "Solution provided",
                                                         "close_notes": "Disk cleaned."})  # fmt: skip
    g.edge("create", "note")
    g.edge("note", "resolve")
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
        keys=KEYS, ssl_context=tls(NAMES).client_context(), types=worker_types([SERVICENOW]),
    )  # fmt: skip
    request = await dev_run.admit(dispatch, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, input={},
                                  simulate=simulate, idempotency_key=f"sn-{simulate}")  # fmt: skip
    async with workers(env.client, DbRunStore(worker, KEYS), plugins=(SERVICENOW,), network=network):
        assert await dispatch_once(dispatch, env.client, KEYS, settings, BUILD) == {"started": 1}
        return request, await dev_run.wait_for_end(dispatch, ctx.tenant_id, request.id, within=90, poll=0.1)


async def test_an_incident_is_created_once_however_its_answer_was_lost_then_noted_and_resolved(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, fake,
) -> None:  # fmt: skip
    server, instance = fake
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings)  # fmt: skip
    _, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=False)
    assert ended == dev_run.Ended("run", "succeeded", None, None), ended
    assert [r.method for r in server.requests] == ["POST", "GET", "PATCH", "PATCH"]  # the retry reconciled
    assert all(r.headers.get("x-sn-apikey") == API_KEY and "authorization" not in r.headers for r in server.requests)
    [incident] = instance.incidents.values()  # one incident, however retried
    key = incident["correlation_id"]
    assert re.fullmatch(r"[0-9a-f]{64}", key) and f"correlation_id={key}" in server.requests[1].target.replace(
        "%3D", "=")  # fmt: skip
    assert (incident["short_description"], incident["urgency"], incident["impact"]) == ("db-1 disk full", "1", "1")
    assert instance.notes == ["Cleaning /var/log."]
    assert (incident["state"], incident["close_code"], incident["close_notes"]) == ("6", "Solution provided",
                                                                                    "Disk cleaned.")  # fmt: skip
    assert all(incident["sys_id"] in r.target for r in server.requests[2:])
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        rows = (await s.execute(text("select node_key, output_preview::text, input_preview::text, status "
                                     "from run_steps"))).all()  # fmt: skip
        scopes = [k for (k,) in (await s.execute(text("select scope from rate_buckets"))).all()]
    assert sorted((r[0], r[3]) for r in rows) == [
        ("create", "failed"),
        ("create", "succeeded"),
        ("note", "succeeded"),
        ("resolve", "succeeded"),
    ]  # a row an attempt
    assert all(API_KEY not in (r[1] or "") + (r[2] or "") for r in rows)
    assert [k.split(":", 1)[0] for k in scopes] == ["servicenow.key"] and API_KEY not in scopes[0]


async def test_a_simulated_incident_workflow_sends_nothing(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, fake,
) -> None:  # fmt: skip
    server, instance = fake
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings)  # fmt: skip
    _, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=True)
    assert ended is not None and ended.status == "succeeded", ended
    assert server.requests == [] and instance.incidents == {}


async def test_a_created_answer_too_deep_to_decode_creates_no_second_incident(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, hidden,
) -> None:  # fmt: skip
    server, instance = hidden
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings)  # fmt: skip
    _, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=False)
    assert ended is not None and ended.status == "failed", ended
    assert [r.method for r in server.requests] == ["POST"] and len(instance.incidents) == 1  # never created again
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        rows = (await s.execute(text("select node_key, status, error_code from run_steps"))).all()
    assert [tuple(r) for r in rows] == [("create", "failed", "servicenow.created_unreadable")]
