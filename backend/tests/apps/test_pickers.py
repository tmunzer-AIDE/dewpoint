# SPDX-License-Identifier: Apache-2.0
"""Start-form pickers at publish (plugins-3 D19): a picker's connection is one of the tenant's, of a type its node may
use, and is recorded in the version's `connection_ids`, so it can't be deleted while an enabled workflow's active
version names it."""

import uuid
from typing import Any

import pytest

from dewpoint.core.connections import service as connections
from tests.apps.test_connection_fields import _delete, connection
from tests.apps.test_workflow_ops import actor, create, publish, update
from tests.support.graphs import G
from tests.support.registry import sync_test_plugins


def graph(connection_id: Any) -> dict[str, Any]:
    g = G().node("e", "testkit.echo@1")
    picker = {"node": "testkit.pick@1", "field": "site_id", "connection": str(connection_id)}
    site = {"type": "string", "x-dewpoint-picker": picker}
    g.settings = {"input_schema": {"type": "object", "properties": {"site": site}}}
    return g.data()


async def test_publish_records_a_pickers_connection(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    cid = await connection(owner_sessionmaker, ctx.tenant_id)
    wf = await create(api_sessionmaker, ctx, graph(cid))
    out = await publish(api_sessionmaker, ctx, wf, api_settings)
    assert out.errors == [] and out.version is not None
    assert out.version.connection_ids == [cid]
    with pytest.raises(connections.ConnectionInUseError):
        await _delete(api_sessionmaker, ctx, cid)
    await update(api_sessionmaker, ctx, wf, enabled=False)
    await _delete(api_sessionmaker, ctx, cid)


@pytest.mark.parametrize("whose", ["missing", "other_tenant", "wrong_type"])
async def test_publish_refuses_a_pickers_connection_the_tenant_doesnt_have_of_its_type(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, whose: str
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx, other = await actor(owner_sessionmaker), await actor(owner_sessionmaker)
    cid = {
        "missing": uuid.uuid4(),
        "other_tenant": await connection(owner_sessionmaker, other.tenant_id),
        "wrong_type": await connection(owner_sessionmaker, ctx.tenant_id, "mist"),
    }[whose]
    wf = await create(api_sessionmaker, ctx, graph(cid))
    out = await publish(api_sessionmaker, ctx, wf, api_settings)
    assert out.version is None
    expected = "picker.connection_wrong_type" if whose == "wrong_type" else "picker.connection_unknown"
    assert {(e.code, e.field) for e in out.errors} == {
        (expected, "/settings/input_schema/properties/site/x-dewpoint-picker")
    }
