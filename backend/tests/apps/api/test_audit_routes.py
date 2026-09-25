# SPDX-License-Identifier: Apache-2.0
from sqlalchemy import select

from dewpoint.core.auth.users import create_user
from dewpoint.core.models.audit import AuditEntry
from tests.apps.api.helpers import PW, session_client


async def test_member_add_is_audited_and_audit_needs_permission(app, owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await create_user(s, email="joiner@corp.test", password=PW)
    admin, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with admin:
        r = await admin.post(f"/api/v1/t/{tid}/members", json={"email": "joiner@corp.test", "role": "viewer"})
        assert r.status_code == 201
        entries = (await admin.get(f"/api/v1/t/{tid}/audit")).json()
    assert entries[0]["action"] == "member.add" and entries[0]["details"] == {"role": "viewer"}
    viewer, vtid = await session_client(app, owner_sessionmaker, api_settings, "viewer")
    async with viewer:
        assert (await viewer.get(f"/api/v1/t/{vtid}/audit")).status_code == 403


async def test_sign_in_events_are_audited_without_secrets(client, owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await create_user(s, email="gil@corp.test", password=PW)
    await client.post("/api/v1/auth/login", json={"email": "gil@corp.test", "password": "wrong-password-123"})
    await client.post("/api/v1/auth/login", json={"email": "gil@corp.test", "password": PW})
    async with owner_sessionmaker() as s:
        rows = (
            (await s.execute(select(AuditEntry).where(AuditEntry.scope == "platform").order_by(AuditEntry.seq)))
            .scalars()
            .all()
        )
    assert [r.action for r in rows] == ["auth.login_failed", "auth.login"]
    dumped = str([(r.details, r.target_id) for r in rows])
    assert "wrong-password-123" not in dumped and PW not in dumped
