# SPDX-License-Identifier: Apache-2.0
"""Connection fields (plugins-3 D6): a literal UUID naming one of the tenant's connections of the type the node's field
declares, checked at publish, which records every one in the version's `connection_ids`; a connection that an enabled
workflow's active closure or a request that hasn't started names can't be deleted."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.core.connections import service as connections
from dewpoint.core.db import tenant_scope
from tests.apps.test_workflow_ops import actor, create, publish, update
from tests.core.requests.test_envelope import admitted
from tests.support.graphs import G, ref
from tests.support.registry import sync_test_plugins

CALL = "testkit.http_call@1"


async def connection(owner: Any, tenant: uuid.UUID, type_key: str = "testkit") -> uuid.UUID:
    cid = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into connections (id, tenant_id, type, name, config) values (:i, :t, :k, :n, '{}')"),
            {"i": cid, "t": tenant, "k": type_key, "n": f"c-{cid.hex[:8]}"},
        )
    return cid


def graph(connection_value: Any) -> dict[str, Any]:
    return G().node("call", CALL, {"connection": connection_value, "path": "/x"}).data()


async def test_publish_records_the_connections_a_version_names(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    cid = await connection(owner_sessionmaker, ctx.tenant_id)
    wf = await create(api_sessionmaker, ctx, graph(str(cid)))
    out = await publish(api_sessionmaker, ctx, wf, api_settings)
    assert out.errors == [] and out.version is not None
    assert out.version.connection_ids == [cid]


@pytest.mark.parametrize("whose", ["missing", "other_tenant", "wrong_type"])
async def test_publish_refuses_a_connection_the_tenant_doesnt_have_of_that_type(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, whose: str
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    other = await actor(owner_sessionmaker)
    cid = {
        "missing": uuid.uuid4(),
        "other_tenant": await connection(owner_sessionmaker, other.tenant_id),
        "wrong_type": await connection(owner_sessionmaker, ctx.tenant_id, "mist"),
    }[whose]
    wf = await create(api_sessionmaker, ctx, graph(str(cid)))
    out = await publish(api_sessionmaker, ctx, wf, api_settings)
    assert out.version is None
    codes = {(e.code, e.field) for e in out.errors}
    expected = "connection.wrong_type" if whose == "wrong_type" else "connection.unknown"
    assert codes == {(expected, "/connection")}


async def test_a_connection_is_written_literally(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, graph(ref("trigger.connection")))
    out = await publish(api_sessionmaker, ctx, wf, api_settings)
    assert out.version is None
    assert any(e.code == "value.literal_only" and e.field == "/connection" for e in out.errors)


async def _delete(api: Any, ctx: Any, cid: uuid.UUID) -> None:
    async with api() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        conn = await connections.get_for_update(s, ctx.tenant_id, cid)
        assert conn is not None
        await connections.delete_connection(s, ctx, conn)


async def test_a_connection_an_enabled_active_version_names_cant_be_deleted(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    cid = await connection(owner_sessionmaker, ctx.tenant_id)
    wf = await create(api_sessionmaker, ctx, graph(str(cid)))
    assert (await publish(api_sessionmaker, ctx, wf, api_settings)).version is not None
    with pytest.raises(connections.ConnectionInUseError):
        await _delete(api_sessionmaker, ctx, cid)
    await update(api_sessionmaker, ctx, wf, enabled=False)
    await _delete(api_sessionmaker, ctx, cid)  # nothing enabled names it now


async def test_a_connection_a_sub_flow_in_the_active_closure_names_cant_be_deleted(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    cid = await connection(owner_sessionmaker, ctx.tenant_id)
    child = await create(api_sessionmaker, ctx, graph(str(cid)), name="Child")
    assert (await publish(api_sessionmaker, ctx, child, api_settings)).version is not None
    await update(api_sessionmaker, ctx, child, enabled=False)
    parent = await create(
        api_sessionmaker, ctx, G().node("r", "flow.run_workflow@1", {"workflow_id": str(child)}).data(), name="Parent"
    )
    assert (await publish(api_sessionmaker, ctx, parent, api_settings)).version is not None
    with pytest.raises(connections.ConnectionInUseError):
        await _delete(api_sessionmaker, ctx, cid)


async def test_a_connection_a_request_not_yet_started_names_cant_be_deleted(
    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    tenant, _request, _ = await admitted(owner_sessionmaker, dispatch_sessionmaker)
    cid = await connection(owner_sessionmaker, tenant)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("alter table workflow_versions disable trigger user"))
        await s.execute(
            text("update workflow_versions set connection_ids = array[cast(:c as uuid)] where tenant_id = :t"),
            {"c": cid, "t": tenant},
        )
        await s.execute(text("alter table workflow_versions enable trigger user"))
        await s.execute(text("update workflows set enabled = false where tenant_id = :t"), {"t": tenant})
    ctx = type("Ctx", (), {"tenant_id": tenant, "user": type("U", (), {"id": None})()})()
    with pytest.raises(connections.ConnectionInUseError):
        await _delete(api_sessionmaker, ctx, cid)
