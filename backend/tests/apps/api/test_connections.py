# SPDX-License-Identifier: Apache-2.0
import uuid

import respx
from sqlalchemy import text

from tests.apps.api.helpers import session_client

ORG = str(uuid.uuid4())
BODY = {
    "type": "mist",
    "name": "Acme Prod",
    "config": {"cloud": "emea_01", "org_id": ORG},
    "secret": {"api_token": "tok_" + "a" * 36},
}


async def test_create_list_never_returns_secret(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        r = await c.post(f"/api/v1/t/{tid}/connections", json=BODY)
        assert r.status_code == 201, r.text
        out = r.json()
        assert out["secret_set"] is True and "secret" not in out and "secret_ct" not in out
        assert "tok_" not in (await c.get(f"/api/v1/t/{tid}/connections")).text
    async with owner_sessionmaker() as s:
        ct = (await s.execute(text("select secret_ct from connections"))).scalar_one()
    assert b"tok_" not in ct


async def test_editor_can_view_not_manage(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        assert (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).status_code == 403
        assert (await c.get(f"/api/v1/t/{tid}/connections")).status_code == 200


async def test_invalid_cloud_and_extra_fields_rejected(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        bad = {**BODY, "config": {"cloud": "evil.example.com", "org_id": ORG}}
        assert (await c.post(f"/api/v1/t/{tid}/connections", json=bad)).status_code == 422
        bad = {**BODY, "config": {**BODY["config"], "host": "evil.example.com"}}
        assert (await c.post(f"/api/v1/t/{tid}/connections", json=bad)).status_code == 422


@respx.mock
async def test_verify_updates_status_and_audits(app, owner_sessionmaker, api_settings) -> None:
    respx.get("https://api.eu.mist.com/api/v1/self").respond(
        200, json={"privileges": [{"scope": "org", "org_id": ORG, "role": "admin"}]}
    )
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).json()["id"]
        r = await c.post(f"/api/v1/t/{tid}/connections/{cid}/verify")
        assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["privilege"] == "admin"
        actions = [e["action"] for e in (await c.get(f"/api/v1/t/{tid}/audit")).json()]
    assert actions[:2] == ["connection.verify", "connection.create"]


async def test_patch_keeps_secret_when_omitted_and_ciphertext_is_bound(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        a = (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).json()["id"]
        b = (await c.post(f"/api/v1/t/{tid}/connections", json={**BODY, "name": "Other"})).json()["id"]
        r = await c.patch(f"/api/v1/t/{tid}/connections/{a}", json={"name": "Renamed"})
        assert r.status_code == 200 and r.json()["secret_set"] is True
        # swapping ciphertext between rows must not decrypt (AAD binds the connection id)
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(
                text("update connections set secret_ct=(select secret_ct from connections where id=:a) where id=:b"),
                {"a": a, "b": b},
            )
        r = await c.post(f"/api/v1/t/{tid}/connections/{b}/verify")
    assert r.status_code == 200
    assert r.json()["status"] == "error" and r.json()["status_detail"] == "secret_unreadable"


async def test_rename_to_existing_name_is_a_conflict(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        await c.post(f"/api/v1/t/{tid}/connections", json=BODY)
        other = (await c.post(f"/api/v1/t/{tid}/connections", json={**BODY, "name": "Other"})).json()["id"]
        r = await c.patch(f"/api/v1/t/{tid}/connections/{other}", json={"name": "Acme Prod"})
    assert r.status_code == 409 and r.json() == {"error": "name_taken"}
