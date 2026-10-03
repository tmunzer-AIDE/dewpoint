# SPDX-License-Identifier: Apache-2.0
"""Retirement and queued requests (engine-core §4.5): a request that hasn't started references its frozen version's
closure. It blocks normal retirement, whether or not its workflow is still enabled; a forced retirement lists it in its
preview, then cancels it explicitly, audited in its tenant, so it never turns into a failure later. A request already
`starting` may still reach Temporal: it isn't cancelled, and a run that starts is never broken by a retirement."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.db import tenant_scope
from dewpoint.core.plugins import lifecycle
from tests.apps.test_admission import admit, current, published
from tests.apps.test_workflow_ops import ECHO_GRAPH, update
from tests.core.requests.test_schema import INSERT_REQUEST, claim
from tests.core.requests.test_schema import request as request_row
from tests.support.workflows import seed_workflow

pytestmark = pytest.mark.usefixtures("development_deployment")
ECHO = lifecycle.Entry("node", "testkit.echo@1")


async def queued(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any) -> tuple[Any, uuid.UUID, Any]:
    ctx, wf = await published(owner, api, admin, settings, graph=ECHO_GRAPH)
    await current(dispatch)
    return ctx, wf, (await admit(api, ctx, wf, input={})).request


async def status(owner: Any, request_id: uuid.UUID) -> tuple[str, str | None, bool]:
    async with owner() as s:
        row = (await s.execute(text("select status, reason, ended_at is not null from run_requests where id = :i"),
                               {"i": request_id})).one()  # fmt: skip
    return row[0], row[1], row[2]


async def test_a_queued_request_blocks_normal_retirement_even_once_its_workflow_is_disabled(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf, request = await queued(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                                    api_settings)  # fmt: skip
    await update(api_sessionmaker, ctx, wf, enabled=False)  # no active reference left: the queued one remains
    with pytest.raises(lifecycle.ReferencedError) as blocked:
        async with admin_sessionmaker() as s, s.begin():
            await lifecycle.retire(s, ECHO)
    assert [(q.tenant_id, q.request_id) for q in blocked.value.preview.queued] == [(ctx.tenant_id, request.id)]


async def test_a_forced_retirement_lists_then_cancels_queued_requests_in_their_tenants(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    made = [await queued(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
            for _ in range(2)]  # fmt: skip
    async with admin_sessionmaker() as s, s.begin():
        preview = await lifecycle.retire(s, ECHO, force=True)
    assert not preview.applied and {q.request_id for q in preview.queued} == {r.id for _, _, r in made}
    async with admin_sessionmaker() as s, s.begin():
        assert (await lifecycle.retire(s, ECHO, force=True, confirm=True)).applied
    for ctx, _, request in made:
        assert await status(owner_sessionmaker, request.id) == ("cancelled", "node_type_retired", True)
        async with owner_sessionmaker() as s:
            details = (await s.execute(text("select details from audit_log where tenant_id = :t and action = "
                                            "'lifecycle.retire'"), {"t": ctx.tenant_id})).scalar_one()  # fmt: skip
        assert details["requests"] == [str(request.id)]


async def test_a_starting_request_blocks_normal_retirement_and_survives_a_forced_one(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf, request = await queued(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                                    api_settings)  # fmt: skip
    await update(api_sessionmaker, ctx, wf, enabled=False)  # only the request references the entry
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(
            text("update run_requests set status = 'starting', starting_at = now() where id = :i"), {"i": request.id}
        )
    with pytest.raises(lifecycle.ReferencedError):
        async with admin_sessionmaker() as s, s.begin():
            await lifecycle.retire(s, ECHO)
    async with admin_sessionmaker() as s, s.begin():
        assert (await lifecycle.retire(s, ECHO, force=True, confirm=True)).applied
    assert await status(owner_sessionmaker, request.id) == ("starting", None, False)


@pytest.mark.parametrize("status", ["starting", "started"])
async def test_the_admin_cancels_only_a_queued_request_even_within_a_tenant_scope(
    owner_sessionmaker, admin_sessionmaker, status
) -> None:
    """The general policy is the operational roles': the admin's only update is a forced retirement's, `queued` to
    `cancelled`, whatever tenant scope its session has set (the owner's M1 checkpoint)."""
    tenant, wf, version = await seed_workflow(owner_sessionmaker)
    values = request_row(tenant, wf, version, status=status)
    async with owner_sessionmaker() as s, s.begin():
        values["envelope_id"] = await claim(s, tenant, values["id"], role="envelope", pointer=None)
        await s.execute(INSERT_REQUEST, values)
    cancel = text("update run_requests set status = 'cancelled', reason = 'r', ended_at = now() where id = :i")
    async with admin_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        assert (await s.execute(cancel, {"i": values["id"]})).rowcount == 0
    async with owner_sessionmaker() as s:
        current = (await s.execute(text("select status from run_requests where id = :i"), {"i": values["id"]})).scalar()
    assert current == status
    queued = request_row(tenant, wf, version)
    async with owner_sessionmaker() as s, s.begin():
        queued["envelope_id"] = await claim(s, tenant, queued["id"], role="envelope", pointer=None)
        await s.execute(INSERT_REQUEST, queued)
    with pytest.raises(DBAPIError, match="row-level security"):  # and only into `cancelled`
        async with admin_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await s.execute(text("update run_requests set status = 'dead', ended_at = now() where id = :i"),
                            {"i": queued["id"]})  # fmt: skip
