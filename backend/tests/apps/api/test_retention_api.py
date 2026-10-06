# SPDX-License-Identifier: Apache-2.0
"""A tenant's retention (engine 2b spec §10.1): `runs_days`, 30 unless its admins set it (`tenant.manage`) within the
platform's bounds, 1 to 365; members who can see the tenant read it."""

from typing import Any

import pytest
from sqlalchemy import text

from tests.apps.api.helpers import member_client
from tests.apps.api.helpers import session_client as _as


async def audited(owner: Any, action: str) -> list[dict[str, Any]]:
    async with owner() as s:
        found = await s.execute(text("select tenant_id, details from audit_log where action = :a order by seq"),
                                {"a": action})  # fmt: skip
        return [dict(r) for r in found.mappings()]


async def test_a_tenant_keeps_its_runs_30_days_unless_its_admins_say_otherwise(app, owner_sessionmaker,
                                                                               api_settings) -> None:  # fmt: skip
    admin, tid = await _as(app, owner_sessionmaker, api_settings, "admin")
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, tid, "viewer")
    async with admin, viewer:
        assert (await viewer.get(f"/api/v1/t/{tid}/retention")).json() == {"runs_days": 30}
        changed = await admin.put(f"/api/v1/t/{tid}/retention", json={"runs_days": 7})
        assert changed.status_code == 200, changed.text
        assert changed.json() == {"runs_days": 7}
        assert (await viewer.get(f"/api/v1/t/{tid}/retention")).json() == {"runs_days": 7}
        assert (await admin.put(f"/api/v1/t/{tid}/retention", json={"runs_days": 365})).json() == {"runs_days": 365}
    entries = await audited(owner_sessionmaker, "tenant.retention.update")
    assert [(e["tenant_id"], e["details"]) for e in entries] == [
        (tid, {"runs_days": 7, "was": 30}), (tid, {"runs_days": 365, "was": 7}),
    ]  # fmt: skip


@pytest.mark.parametrize("body", [{"runs_days": 0}, {"runs_days": 366}, {"runs_days": "30"}, {}, {"days": 30},
                                  {"runs_days": 30, "other": 1}])  # fmt: skip
async def test_a_retention_outside_the_platforms_bounds_is_refused(app, owner_sessionmaker, api_settings,
                                                                   body: dict[str, Any]) -> None:  # fmt: skip
    admin, tid = await _as(app, owner_sessionmaker, api_settings, "admin")
    async with admin:
        assert (await admin.put(f"/api/v1/t/{tid}/retention", json=body)).status_code == 422
        assert (await admin.get(f"/api/v1/t/{tid}/retention")).json() == {"runs_days": 30}
    assert await audited(owner_sessionmaker, "tenant.retention.update") == []


@pytest.mark.parametrize(("method", "body", "expect"), [
    ("GET", None, {"viewer": 200, "admin": 200, None: 404}),
    ("PUT", {"runs_days": 10}, {"viewer": 403, "operator": 403, "editor": 403, "admin": 200, "owner": 200, None: 404}),
])  # fmt: skip
async def test_who_reads_and_who_sets_a_tenants_retention(
    app, owner_sessionmaker, api_settings, method: str, body: Any, expect: dict[str | None, int]
) -> None:
    for role, status in expect.items():
        c, tid = await _as(app, owner_sessionmaker, api_settings, role)
        async with c:
            assert (await c.request(method, f"/api/v1/t/{tid}/retention", json=body)).status_code == status, role


async def test_the_api_reads_and_sets_only_its_own_tenants_retention(app, owner_sessionmaker, api_settings) -> None:
    """Row-level security: one tenant's admin, setting its retention, leaves another tenant's alone."""
    first, a = await _as(app, owner_sessionmaker, api_settings, "admin")
    second, b = await _as(app, owner_sessionmaker, api_settings, "admin")
    async with first, second:
        await first.put(f"/api/v1/t/{a}/retention", json={"runs_days": 3})
        await second.put(f"/api/v1/t/{b}/retention", json={"runs_days": 90})
        assert (await first.get(f"/api/v1/t/{a}/retention")).json() == {"runs_days": 3}
        assert (await second.get(f"/api/v1/t/{b}/retention")).json() == {"runs_days": 90}
    async with owner_sessionmaker() as s:
        rows = (await s.execute(text("select tenant_id, runs_days from tenant_retention order by runs_days"))).all()
    assert [tuple(r) for r in rows] == [(a, 3), (b, 90)]
