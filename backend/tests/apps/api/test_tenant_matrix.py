# SPDX-License-Identifier: Apache-2.0
import uuid

import pytest
from sqlalchemy import text

from tests.apps.api.helpers import session_client as _as

PW = "violet-otter-canyon-42"


CASES = [
    # (method, path, body, {role: expected_status})
    ("GET", "/api/v1/t/{t}", None, {"viewer": 200, "owner": 200, None: 404}),
    ("PATCH", "/api/v1/t/{t}", {"name": "New"}, {"viewer": 403, "editor": 403, "admin": 200, None: 404}),
    ("GET", "/api/v1/t/{t}/members", None, {"viewer": 200, None: 404}),
    (
        "POST",
        "/api/v1/t/{t}/members",
        {"email": "nobody@corp.test", "role": "viewer"},
        {"operator": 403, "admin": 404, None: 404},
    ),  # admin allowed; unknown user -> 404 user_not_found
]


@pytest.mark.parametrize("method,path,body,expect", CASES)
async def test_permission_matrix(app, owner_sessionmaker, api_settings, method, path, body, expect) -> None:
    for role, status in expect.items():
        c, tid = await _as(app, owner_sessionmaker, api_settings, role)
        async with c:
            r = await c.request(method, path.format(t=tid), json=body)
        assert r.status_code == status, (role, r.text)


async def test_enroll_required_session_blocked(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await _as(app, owner_sessionmaker, api_settings, "owner")
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update sessions set state='enroll_required'"))
    async with c:
        assert (await c.get("/api/v1/tenants")).status_code == 403
        assert (await c.get(f"/api/v1/t/{tid}")).status_code == 403


async def test_require_passkey_step_up(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await _as(app, owner_sessionmaker, api_settings, "owner", require_passkey=True)
    async with c:
        r = await c.get(f"/api/v1/t/{tid}")
    assert r.status_code == 403 and r.json() == {"error": "step_up_required"}
    c, tid = await _as(app, owner_sessionmaker, api_settings, "owner", methods=("passkey",), require_passkey=True)
    async with c:
        assert (await c.get(f"/api/v1/t/{tid}")).status_code == 200


async def test_platform_admin_creates_tenant_and_last_owner_protected(app, owner_sessionmaker, api_settings) -> None:
    c, _ = await _as(app, owner_sessionmaker, api_settings, None, platform_admin=True)
    async with c:
        r = await c.post("/api/v1/tenants", json={"name": "Acme Retail", "slug": "acme-retail"})
        assert r.status_code == 201
        tid = r.json()["id"]
        mine = (await c.get("/api/v1/tenants")).json()
        assert [(t["slug"], t["role"]) for t in mine] == [("acme-retail", "owner")]
        me = (await c.get("/api/v1/auth/session")).json()["user"]["id"]
        r = await c.patch(f"/api/v1/t/{tid}/members/{me}", json={"role": "admin"})
        assert r.status_code == 409 and r.json() == {"error": "last_owner"}


async def test_unfiltered_query_after_require_sees_only_current_tenant(app, owner_sessionmaker, api_settings) -> None:
    from fastapi import APIRouter, Depends
    from sqlalchemy import select

    from dewpoint.core.authz.permissions import P
    from dewpoint.core.http import get_db, require
    from dewpoint.core.models.tenancy import Membership, Tenant

    router = APIRouter()

    @router.get("/api/v1/t/{tenant_id}/_probe")
    async def probe(_=Depends(require(P.TENANT_VIEW)), db=Depends(get_db)) -> dict[str, int]:
        return {
            "memberships": len((await db.execute(select(Membership))).scalars().all()),  # deliberately unfiltered
            "tenants": len((await db.execute(select(Tenant))).scalars().all()),
        }

    app.include_router(router)
    c, tid = await _as(app, owner_sessionmaker, api_settings, "owner")
    other = uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():  # same user also owns a second tenant
        await s.execute(
            text("insert into tenants(id,name,slug) values (:o,'O',:slug)"), {"o": other, "slug": other.hex[:12]}
        )
        await s.execute(
            text(
                "insert into memberships(tenant_id,user_id,role) select :o, user_id, 'owner' "
                "from memberships where tenant_id=:t"
            ),
            {"o": other, "t": tid},
        )
    async with c:
        assert (await c.get(f"/api/v1/t/{tid}/_probe")).json() == {"memberships": 1, "tenants": 1}


async def test_non_admin_cannot_create_tenant(app, owner_sessionmaker, api_settings) -> None:
    c, _ = await _as(app, owner_sessionmaker, api_settings, "owner")
    async with c:
        assert (await c.post("/api/v1/tenants", json={"name": "X", "slug": "x-tenant"})).status_code == 403


async def test_platform_admin_creates_users(app, owner_sessionmaker, api_settings) -> None:
    admin, _ = await _as(app, owner_sessionmaker, api_settings, None, platform_admin=True)
    async with admin:
        r = await admin.post("/api/v1/admin/users", json={"email": "new@site.local", "password": PW})
        assert r.status_code == 201 and r.json()["email"] == "new@site.local"
        r = await admin.post("/api/v1/admin/users", json={"email": "NEW@site.local", "password": PW})
        assert r.status_code == 409 and r.json() == {"error": "email_taken"}
        r = await admin.post("/api/v1/admin/users", json={"email": "weak@site.local", "password": "short"})
        assert r.status_code == 422 and r.json()["error"] == "password_policy"
        assert "short" not in r.text
    owner, _ = await _as(app, owner_sessionmaker, api_settings, "owner")
    async with owner:
        r = await owner.post("/api/v1/admin/users", json={"email": "x@site.local", "password": PW})
        assert r.status_code == 403
