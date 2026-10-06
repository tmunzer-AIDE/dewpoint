# SPDX-License-Identifier: Apache-2.0
"""A tenant's erasure through the API (2b-4a M4; D11's identity rule): a platform admin, on an active MFA session with a
second factor proven within the reauthentication window, starts it by typing the tenant's slug, and may stop it, retry
it and read it; who asked is that admin's user id, in the record and the audit. Irreversible: a second start is refused,
and nothing returns the tenant to active."""

import uuid
from typing import Any

from sqlalchemy import text

from tests.apps.api.helpers import session_client


async def admin_of(app: Any, owner: Any, settings: Any, *, fresh: bool = True) -> tuple[Any, uuid.UUID]:
    """A platform admin's client (on a tenant of its own, which it doesn't erase), its second factor proven now."""
    client, _ = await session_client(app, owner, settings, None, platform_admin=True)
    async with owner() as s, s.begin():
        user_id = (await s.execute(text("select user_id from sessions order by created_at desc limit 1"))).scalar_one()
        if fresh:
            await s.execute(text("update sessions set reauth_at = now() where user_id = :u"), {"u": user_id})
    return client, user_id


async def tenant_of(app: Any, owner: Any, settings: Any) -> tuple[uuid.UUID, str]:
    member, tenant = await session_client(app, owner, settings, "owner")
    await member.aclose()
    async with owner() as s:
        return tenant, (await s.execute(text("select slug from tenants where id = :t"), {"t": tenant})).scalar_one()


def url(tenant: uuid.UUID, tail: str = "") -> str:
    return f"/api/v1/admin/tenants/{tenant}/erasure{tail}"


async def test_a_platform_admin_starts_an_erasure_by_typing_the_slug_and_reads_it(
    app, owner_sessionmaker, api_settings
) -> None:
    admin, admin_id = await admin_of(app, owner_sessionmaker, api_settings)
    tenant, slug = await tenant_of(app, owner_sessionmaker, api_settings)
    async with admin:
        wrong = await admin.post(url(tenant), json={"confirm": "not-" + slug})
        assert (wrong.status_code, wrong.json()) == (422, {"error": "confirmation_mismatch"})
        started = await admin.post(url(tenant), json={"confirm": slug})
        assert started.status_code == 202, started.text
        assert (started.json()["step"], started.json()["step_name"]) == (20, "reconcile")
        again = await admin.post(url(tenant), json={"confirm": slug})
        assert (again.status_code, again.json()) == (409, {"error": "not_erasable"})
        shown = (await admin.get(url(tenant))).json()
        assert (shown["requested_by"], shown["stopped_at"], shown["completed_at"]) == (str(admin_id), None, None)
        assert (await admin.get(url(uuid.uuid4()))).status_code == 404
        assert (await admin.post(url(uuid.uuid4()), json={"confirm": "x"})).status_code == 404
    async with owner_sessionmaker() as s:
        status = (await s.execute(text("select status from tenants where id = :t"), {"t": tenant})).scalar_one()
        actor = (await s.execute(text("select actor_id from audit_log where action = 'tenant.erasure.start'"))).scalar()
    assert (status, actor) == ("erasing", admin_id)


async def test_an_operator_stops_and_retries_it_and_neither_reverses_it(app, owner_sessionmaker, api_settings) -> None:
    admin, admin_id = await admin_of(app, owner_sessionmaker, api_settings)
    tenant, slug = await tenant_of(app, owner_sessionmaker, api_settings)
    async with admin:
        assert (await admin.post(url(tenant, "/stop"))).status_code == 404  # nothing under way
        assert (await admin.post(url(tenant), json={"confirm": slug})).status_code == 202
        stopped = (await admin.post(url(tenant, "/stop"))).json()
        assert (stopped["stopped_by"], stopped["stopped_at"] is not None) == (str(admin_id), True)
        retried = (await admin.post(url(tenant, "/retry"))).json()
        assert (retried["stopped_by"], retried["stopped_at"]) == (None, None)
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select status from tenants where id = :t"), {"t": tenant})).scalar() == "erasing"


async def test_only_a_platform_admin_with_a_fresh_second_factor_erases(app, owner_sessionmaker, api_settings) -> None:
    tenant, slug = await tenant_of(app, owner_sessionmaker, api_settings)
    member, own = await session_client(app, owner_sessionmaker, api_settings, "owner")  # its own tenant's owner
    async with owner_sessionmaker() as s:
        own_slug = (await s.execute(text("select slug from tenants where id = :t"), {"t": own})).scalar_one()
    async with member:
        refused = await member.post(url(own), json={"confirm": own_slug})
        assert (refused.status_code, refused.json()) == (403, {"error": "forbidden"})
        assert (await member.get(url(own))).status_code == 403
    stale, _ = await admin_of(app, owner_sessionmaker, api_settings, fresh=False)
    async with stale:
        refused = await stale.post(url(tenant), json={"confirm": slug})
        assert (refused.status_code, refused.json()) == (403, {"error": "reauth_required"})
    async with owner_sessionmaker() as s:
        statuses = set((await s.execute(text("select status from tenants where id in (:a, :b)"),
                                        {"a": tenant, "b": own})).scalars())  # fmt: skip
    assert statuses == {"active"}
