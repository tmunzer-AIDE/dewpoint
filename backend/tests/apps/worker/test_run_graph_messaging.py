# SPDX-License-Identifier: Apache-2.0
"""3c-1's proof (plugins-3 D18), end to end: a published workflow posting one message to Slack, Teams, Google Chat and
a webhook, and a body of the workflow's to the webhook, runs through admission, the dispatcher and RunGraph against
one local fake standing in for `hooks.slack.com`, a Workflows host, `chat.googleapis.com` and a receiver (each vetted,
pinned and TLS-checked by the guard; their port 443 redirected in the test's socket layer only):

- each request goes to its connection's URL exactly - its path and query, nothing of the node's - with no
  authentication header, its body the target's rendering of the message;
- each step's output is what the target's answer establishes, and no step's row holds a URL's secret;
- each send charges its type's quota scope;
- simulated, the same workflow sends nothing."""

import asyncio
import ipaddress
import json
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
from dewpoint.plugins.google_chat import PLUGIN as CHAT
from dewpoint.plugins.slack import PLUGIN as SLACK
from dewpoint.plugins.teams import PLUGIN as TEAMS
from dewpoint.plugins.webhook import PLUGIN as WEBHOOK
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
SLACK_HOST, TEAMS_HOST, CHAT_HOST, HOOK_HOST = (
    "hooks.slack.com", "prod-00.westus.logic.azure.com", "chat.googleapis.com", "hooks.example.com",
)  # fmt: skip
NAMES = (SLACK_HOST, TEAMS_HOST, CHAT_HOST, HOOK_HOST)
SLACK_TARGET = "/services/T0001ABCD/B0002EFGH/" + "s" * 24
TEAMS_TARGET = ("/workflows/0a1b2c3d/triggers/manual/paths/invoke?api-version=2016-06-01"
                "&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=" + "t" * 43)  # fmt: skip
CHAT_TARGET = "/v1/spaces/AAAAbCd12/messages?key=AIzaSy" + "k" * 33 + "&token=" + "c" * 40 + "%3D"
HOOK_TARGET = "/in/alerts?token=" + "w" * 32
URLS = {
    "slack": ("webhook_url", f"https://{SLACK_HOST}{SLACK_TARGET}"),
    "teams": ("webhook_url", f"https://{TEAMS_HOST}{TEAMS_TARGET}"),
    "google_chat": ("webhook_url", f"https://{CHAT_HOST}{CHAT_TARGET}"),
    "webhook": ("url", f"https://{HOOK_HOST}{HOOK_TARGET}"),
}
SECRETS = ["s" * 24, "t" * 43, "k" * 33, "c" * 40, "w" * 32]
MESSAGE = {"title": "db-1", "text": "Disk full on <db-1>", "fields": [{"label": "Free", "value": "2%"}],
           "links": [{"label": "Runbook", "url": "https://wiki.example.com/disk"}], "severity": "warning"}  # fmt: skip


def answer(writer: asyncio.StreamWriter, status: int, body: bytes = b"", kind: str = "application/json") -> None:
    writer.write(f"HTTP/1.1 {status} X\r\ncontent-type: {kind}\r\ncontent-length: {len(body)}\r\n\r\n".encode() + body)


@pytest.fixture
async def fakes(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Server]:
    """Each target's success: Slack's 200 `ok`, the flow's 202, Chat's created message, the receiver's 204."""

    async def targets(request: Request, writer: asyncio.StreamWriter) -> None:
        host = request.headers.get("host")
        if (host, request.target) == (SLACK_HOST, SLACK_TARGET):
            answer(writer, 200, b"ok", "text/plain")
        elif (host, request.target) == (TEAMS_HOST, TEAMS_TARGET):
            answer(writer, 202)
        elif (host, request.target) == (CHAT_HOST, CHAT_TARGET):
            answer(writer, 200, json.dumps({"name": "spaces/AAAAbCd12/messages/m1"}).encode())
        elif (host, request.target) == (HOOK_HOST, HOOK_TARGET):
            answer(writer, 204)
        else:
            answer(writer, 404)
        await writer.drain()

    async with serve_http(targets, tls_names=NAMES) as server:
        connect_tcp = httpcore.AnyIOBackend.connect_tcp

        async def redirected(self: Any, host: str, port: int, *args: Any, **kwargs: Any) -> Any:
            return await connect_tcp(self, host, server.port if (host, port) == ("127.0.0.1", 443) else port, *args,
                                     **kwargs)  # fmt: skip

        monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", redirected)
        yield server


async def _published(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any) -> tuple[Any, uuid.UUID]:
    async with admin() as s, s.begin():
        await sync_installed(s, [FLOW, SLACK, TEAMS, CHAT, WEBHOOK])
    ctx = await actor(owner)
    ids = {}
    for kind, (field, url) in URLS.items():
        ids[kind] = str(await add_connection(owner, ctx.tenant_id, type_key=kind, config={}, secret={field: url}))
    g = G()
    g.node("slack", "slack.send_message@1", {"connection": ids["slack"], **MESSAGE})
    g.node("teams", "teams.send_message@1", {"connection": ids["teams"], **MESSAGE})
    g.node("chat", "google_chat.send_message@1", {"connection": ids["google_chat"], **MESSAGE})
    g.node("hook", "webhook.send_message@1", {"connection": ids["webhook"], **MESSAGE})
    body = {"event": "disk_full", "slack": ref("steps.slack.output")}  # a template body: a ref resolved at run time
    g.node("json", "webhook.send_json@1", {"connection": ids["webhook"], "body": body})
    for a, b in [("slack", "teams"), ("teams", "chat"), ("chat", "hook"), ("hook", "json")]:
        g.edge(a, b)
    wf = await create(api, ctx, g.data())
    published = await publish(api, ctx, wf, settings)
    assert published.version is not None, published
    await current(dispatch)
    await ready_workers(owner)
    return ctx, wf


async def _run(env: Any, ctx: Any, wf: Any, dispatch: Any, worker: Any, settings: Any, *, simulate: bool) -> Any:
    loopback = AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, ctx.tenant_id)
    plugins = (SLACK, TEAMS, CHAT, WEBHOOK)
    network = Network(
        guard=guard({name: ["127.0.0.1"] for name in NAMES}, [loopback]),
        connections=DbConnections(worker),
        sessionmaker=worker,
        keys=KEYS,
        ssl_context=tls(NAMES).client_context(),
        types=worker_types(list(plugins)),
    )
    request = await dev_run.admit(dispatch, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, input={},
                                  simulate=simulate, idempotency_key=f"m-{simulate}")  # fmt: skip
    async with workers(env.client, DbRunStore(worker, KEYS), plugins=plugins, network=network):
        assert await dispatch_once(dispatch, env.client, KEYS, settings, BUILD) == {"started": 1}
        return request, await dev_run.wait_for_end(dispatch, ctx.tenant_id, request.id, within=90, poll=0.1)


async def test_one_message_reaches_every_target_at_its_url_exactly(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, fakes,
) -> None:  # fmt: skip
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings)  # fmt: skip
    _, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=False)
    assert ended == dev_run.Ended("run", "succeeded", None, None), ended
    sent = [(r.method, r.headers.get("host"), r.target) for r in fakes.requests]
    assert sent == [("POST", SLACK_HOST, SLACK_TARGET), ("POST", TEAMS_HOST, TEAMS_TARGET),
                    ("POST", CHAT_HOST, CHAT_TARGET), ("POST", HOOK_HOST, HOOK_TARGET),
                    ("POST", HOOK_HOST, HOOK_TARGET)]  # fmt: skip
    assert all("authorization" not in r.headers and "cookie" not in r.headers for r in fakes.requests)
    slack, teams, chat, hook, body = (json.loads(r.body) for r in fakes.requests)
    assert slack["blocks"][0]["text"]["text"] == "*db-1*" and "&lt;db-1&gt;" in slack["blocks"][1]["text"]["text"]
    card = teams["attachments"][0]["content"]
    assert card["body"][1]["inlines"][0]["text"] == "Disk full on <db-1>"  # a text run renders no markdown
    assert chat == {"text": "*db-1*\nDisk full on ＜db-1＞\n\n*Free*: 2%\n\n<https://wiki.example.com/disk|Runbook>\n\n"
                            "Severity: warning"}  # fmt: skip
    assert hook == MESSAGE
    assert body == {"event": "disk_full", "slack": {"sent": True, "truncated": []}}
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        rows = (await s.execute(text("select node_key, output_preview::text, input_preview::text, status "
                                     "from run_steps"))).all()  # fmt: skip
        scopes = [k for (k,) in (await s.execute(text("select scope from rate_buckets"))).all()]
    assert sorted((r[0], r[3]) for r in rows) == [(k, "succeeded") for k in ("chat", "hook", "json", "slack", "teams")]
    assert not [r[0] for r in rows for secret in SECRETS if secret in (r[1] or "") + (r[2] or "")]
    previews = {r[0]: json.loads(r[1]) for r in rows}
    assert previews == {
        "slack": {"sent": True, "truncated": []}, "teams": {"accepted": True, "truncated": []},
        "chat": {"sent": True, "truncated": []}, "hook": {"sent": True, "status": 204},
        "json": {"sent": True, "status": 204},
    }  # fmt: skip
    kinds = sorted({k.split(":", 1)[0] for k in scopes})
    assert kinds == ["google_chat.space", "slack.tenant", "teams.tenant", "webhook.host"]
    assert not [k for k in scopes for secret in SECRETS if secret in k]  # keyed by a MAC, never the URL's part


async def test_a_simulated_messaging_workflow_sends_nothing(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, fakes,
) -> None:  # fmt: skip
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings)  # fmt: skip
    _, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=True)
    assert ended is not None and ended.status == "succeeded", ended
    assert fakes.requests == []
