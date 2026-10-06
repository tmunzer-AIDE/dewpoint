# SPDX-License-Identifier: Apache-2.0
"""The worker serves plugin calls (plugins-3 D3), against local servers only. It claims only calls whose node or type
its build has; the hook runs read-only (GET and HEAD, refused before anything is sent), through the call's own
connection only, at the revision the API read, within a deadline; its answer is checked (shape, size, no secret of
the connection in it) and sealed under the tenant's key, or the call fails with a fixed code."""

import asyncio
import ipaddress
import json
import uuid
from typing import Any

import pytest
import structlog
from sqlalchemy import text

from dewpoint.apps.worker.network import DbConnections, Network
from dewpoint.apps.worker.plugin_calls import PluginCallServer, _Refused, _verify_answer
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.db import tenant_scope
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.core.plugins import calls
from dewpoint.sdk import VerifyResult
from tests.support.connections import add_connection, seed_step, types_for_testkit
from tests.support.keys import FixtureKeys
from tests.support.netfakes import Request, guard, serve, tls
from tests.support.plugins.testkit import TESTKIT

NAMES = ("dewpoint.test",)
TOKEN = "s3cr3t-token-value"
SITES = [{"id": "s1", "name": "Site 1"}, {"id": "s2", "name": "Site 2"}]


async def service(request: Request, writer: asyncio.StreamWriter) -> None:
    if request.target.startswith("/sites") and request.method == "GET":
        body = json.dumps(SITES).encode()
        if "q=echo" in request.target:
            body = request.headers.get("authorization", "").encode()
    elif request.target == "/verify":
        body = b"{}"
    else:
        body = b"no"
    writer.write(f"HTTP/1.1 200 X\r\ncontent-length: {len(body)}\r\n\r\n".encode() + body)
    await writer.drain()


def server_for(worker: Any, tenant: uuid.UUID, *, types: Any = None, plugins: Any = (TESTKIT,), **kw: Any) -> Any:
    network = Network(
        guard=guard({"dewpoint.test": ["127.0.0.1"]}, [AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, tenant)]),
        connections=DbConnections(worker),
        sessionmaker=worker,
        keys=FixtureKeys(),
        ssl_context=tls(NAMES).client_context(),
        types=types_for_testkit() if types is None else types,
    )
    return PluginCallServer(worker, network, list(plugins), **kw)


async def setup(owner: Any, port: int) -> tuple[uuid.UUID, uuid.UUID]:
    tenant = uuid.uuid4()
    await seed_step(owner, named=[None], tenant=tenant)  # creates the tenant
    cid = await add_connection(owner, tenant, config={"base_url": f"https://dewpoint.test:{port}"})
    return tenant, cid


async def ask(api: Any, tenant: uuid.UUID, cid: uuid.UUID | None, q: str = "pa", *, revision: int = 1,
              ref: str = "testkit.pick@1", field: str = "site_id") -> uuid.UUID:  # fmt: skip
    async with api() as s, s.begin():
        await tenant_scope(s, tenant)
        return await calls.ask_options(
            s, tenant, node_ref=ref, field=field, connection_id=cid, revision=revision if cid else None, query=q
        )


async def outcome(api: Any, tenant: uuid.UUID, call: uuid.UUID) -> tuple[str, Any]:
    async with api() as s, s.begin():
        await tenant_scope(s, tenant)
        found = await calls.read(s, tenant, call)
    assert found is not None
    if found.state != "done":
        return found.state, found.error
    assert found.result_ct is not None
    opened = await ClaimCipher(FixtureKeys(), purpose=calls.PURPOSE).open(str(tenant), str(call), found.result_ct)
    return found.state, json.loads(opened)


async def test_options_are_listed_through_the_calls_connection(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask(api_sessionmaker, tenant, cid)
        assert await server_for(worker_sessionmaker, tenant).serve_once() == 1
    assert await outcome(api_sessionmaker, tenant, call) == (
        "done", {"options": [{"value": "s1", "label": "Site 1"}, {"value": "s2", "label": "Site 2"}]},
    )  # fmt: skip
    (request,) = fake.requests
    assert (request.method, request.target, request.headers["authorization"]) == (
        "GET",
        "/sites?q=pa",
        f"Bearer {TOKEN}",
    )


async def test_the_answer_is_sealed(owner_sessionmaker, api_sessionmaker, worker_sessionmaker) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask(api_sessionmaker, tenant, cid)
        await server_for(worker_sessionmaker, tenant).serve_once()
    async with owner_sessionmaker() as s:
        stored = (await s.execute(text("select result_ct from plugin_calls where id = :i"), {"i": call})).scalar_one()
    assert b"Site 1" not in stored


@pytest.mark.parametrize("q", ["post", "plain", "getbody", "override"])
async def test_a_hook_may_only_read(owner_sessionmaker, api_sessionmaker, worker_sessionmaker, q: str) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask(api_sessionmaker, tenant, cid, q)
        await server_for(worker_sessionmaker, tenant).serve_once()
    assert await outcome(api_sessionmaker, tenant, call) == ("failed", "read_only")
    assert fake.requests == []


async def test_an_answer_holding_the_connections_secret_is_refused(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask(api_sessionmaker, tenant, cid, "echo")
        await server_for(worker_sessionmaker, tenant).serve_once()
    assert await outcome(api_sessionmaker, tenant, call) == ("failed", "result_refused")


async def test_too_many_options_are_refused(owner_sessionmaker, api_sessionmaker, worker_sessionmaker) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask(api_sessionmaker, tenant, cid, "many")
        await server_for(worker_sessionmaker, tenant).serve_once()
    assert await outcome(api_sessionmaker, tenant, call) == ("failed", "result_too_large")


async def test_a_hook_opens_only_the_calls_connection(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        sibling = await add_connection(
            owner_sessionmaker, tenant, config={"base_url": f"https://dewpoint.test:{fake.port}"}
        )
        call = await ask(api_sessionmaker, tenant, cid, f"other:{sibling}")
        await server_for(worker_sessionmaker, tenant).serve_once()
    assert await outcome(api_sessionmaker, tenant, call) == ("failed", "connection_unavailable")
    assert fake.requests == []


async def test_a_connection_changed_since_the_api_read_it_sends_nothing(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask(api_sessionmaker, tenant, cid, revision=1)
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("update connections set revision = 2 where id = :c"), {"c": cid})
        await server_for(worker_sessionmaker, tenant).serve_once()
    assert await outcome(api_sessionmaker, tenant, call) == ("failed", "connection_changed")
    assert fake.requests == []


async def test_another_tenants_connection_is_unavailable(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        _, theirs = await setup(owner_sessionmaker, fake.port)
        mine, _ = await setup(owner_sessionmaker, fake.port)
        call = await ask(api_sessionmaker, mine, None)
        async with owner_sessionmaker() as s, s.begin():  # a call naming another tenant's connection
            await s.execute(
                text("update plugin_calls set connection_id = :c, connection_revision = 1 where id = :i"),
                {"c": theirs, "i": call},
            )
        await server_for(worker_sessionmaker, mine).serve_once()
    assert await outcome(api_sessionmaker, mine, call) == ("failed", "connection_unavailable")
    assert fake.requests == []


async def test_a_failing_hook_is_logged_by_its_type_never_its_message(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask(api_sessionmaker, tenant, cid, "boom")
        with structlog.testing.capture_logs() as logs:
            await server_for(worker_sessionmaker, tenant).serve_once()
    assert await outcome(api_sessionmaker, tenant, call) == ("failed", "plugin_failed")
    assert "must not be logged" not in repr(logs)
    assert any(entry.get("error") == "RuntimeError" for entry in logs)


async def test_a_slow_hook_times_out(owner_sessionmaker, api_sessionmaker, worker_sessionmaker) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask(api_sessionmaker, tenant, cid, "slow")
        await server_for(worker_sessionmaker, tenant, call_timeout_s=0.3).serve_once()
    assert await outcome(api_sessionmaker, tenant, call) == ("failed", "timeout")


async def test_only_an_options_field_is_asked(owner_sessionmaker, api_sessionmaker, worker_sessionmaker) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask(api_sessionmaker, tenant, cid, field="note")
        await server_for(worker_sessionmaker, tenant).serve_once()
    assert await outcome(api_sessionmaker, tenant, call) == ("failed", "invalid_field")
    assert fake.requests == []


async def test_a_worker_without_the_code_leaves_the_call(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        call = await ask(api_sessionmaker, tenant, cid)
        assert await server_for(worker_sessionmaker, tenant, plugins=(), types={}).serve_once() == 0
    assert await outcome(api_sessionmaker, tenant, call) == ("pending", None)


async def test_a_connection_type_is_verified(owner_sessionmaker, api_sessionmaker, worker_sessionmaker) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            call = await calls.ask_verify(s, tenant, connection_type="testkit", connection_id=cid, revision=1)
        await server_for(worker_sessionmaker, tenant).serve_once()
    assert await outcome(api_sessionmaker, tenant, call) == ("done", {"ok": True, "detail": "ok", "privilege": None})
    assert [(r.method, r.target) for r in fake.requests] == [("GET", "/verify")]


async def test_a_notification_wakes_the_server(owner_sessionmaker, api_sessionmaker, worker_sessionmaker) -> None:
    async with serve(service, tls_names=NAMES) as fake:
        tenant, cid = await setup(owner_sessionmaker, fake.port)
        server = server_for(worker_sessionmaker, tenant, poll_s=60)
        running = asyncio.create_task(server.run())
        try:
            await asyncio.wait_for(server.listening.wait(), 10)
            async with api_sessionmaker() as s, s.begin():
                await tenant_scope(s, tenant)
                call = await calls.ask_options(s, tenant, node_ref="testkit.pick@1", field="site_id",
                                               connection_id=cid, revision=1, query="pa")  # fmt: skip
                await calls.notify(s)
            for _ in range(100):
                if (await outcome(api_sessionmaker, tenant, call))[0] == "done":
                    break
                await asyncio.sleep(0.05)
        finally:
            server.stop()
            await asyncio.wait_for(running, 10)
    assert (await outcome(api_sessionmaker, tenant, call))[0] == "done"


@pytest.mark.parametrize(
    "result",
    [
        VerifyResult(True, "x" * 41),
        VerifyResult(True, "ok", "p" * 41),
        VerifyResult(True, "Not_A_Code"),
    ],
)
def test_a_verification_fits_what_is_stored(result: VerifyResult) -> None:
    """`status_detail` and `privilege` are 40 characters (the 3a-2 review's finding 4): a longer one is refused as an
    invalid result rather than failing the write and leaving an older status in place."""
    with pytest.raises(_Refused) as raised:
        _verify_answer(result)
    assert raised.value.code == "invalid_result"
