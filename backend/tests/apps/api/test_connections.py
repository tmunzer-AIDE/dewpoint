# SPDX-License-Identifier: Apache-2.0
import asyncio
import uuid

import httpx
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


def _paused_mist(release: asyncio.Event, started: asyncio.Event) -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        started.set()
        await release.wait()  # hold the verification in flight
        return httpx.Response(200, json={"privileges": [{"scope": "org", "org_id": ORG, "role": "admin"}]})

    respx.get("https://api.eu.mist.com/api/v1/self").mock(side_effect=slow)


@respx.mock
async def test_verification_does_not_certify_credentials_edited_in_flight(
    app, owner_sessionmaker, api_settings
) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    started, release = asyncio.Event(), asyncio.Event()
    _paused_mist(release, started)
    async with c:
        cid = (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).json()["id"]
        verify = asyncio.create_task(c.post(f"/api/v1/t/{tid}/connections/{cid}/verify"))
        try:
            await asyncio.wait_for(started.wait(), 10)  # verification loaded revision 1 and is talking to "Mist"
            new_secret = {"secret": {"api_token": "tok_" + "b" * 36}}
            edited = await c.patch(f"/api/v1/t/{tid}/connections/{cid}", json=new_secret)
        finally:
            release.set()  # never leave the paused request (and its DB connection) hanging
            r = await asyncio.wait_for(verify, 10)
        assert edited.status_code == 200 and edited.json()["revision"] == 2
        assert r.status_code == 409 and r.json() == {"error": "changed_during_verification"}
        after = (await c.get(f"/api/v1/t/{tid}/connections/{cid}")).json()
        actions = [e["action"] for e in (await c.get(f"/api/v1/t/{tid}/audit")).json()]
    assert after["status"] == "unverified" and after["revision"] == 2  # the edit's state survives
    assert actions[0] == "connection.verify_discarded"


@respx.mock
async def test_rename_during_verification_keeps_the_result(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    started, release = asyncio.Event(), asyncio.Event()
    _paused_mist(release, started)
    async with c:
        cid = (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).json()["id"]
        verify = asyncio.create_task(c.post(f"/api/v1/t/{tid}/connections/{cid}/verify"))
        try:
            await asyncio.wait_for(started.wait(), 10)
            await c.patch(f"/api/v1/t/{tid}/connections/{cid}", json={"name": "Renamed"})  # not a credential change
        finally:
            release.set()
            r = await asyncio.wait_for(verify, 10)
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["name"] == "Renamed"


@respx.mock
async def test_delete_during_verification_is_not_found(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    started, release = asyncio.Event(), asyncio.Event()
    _paused_mist(release, started)
    async with c:
        cid = (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).json()["id"]
        verify = asyncio.create_task(c.post(f"/api/v1/t/{tid}/connections/{cid}/verify"))
        try:
            await asyncio.wait_for(started.wait(), 10)
            deleted = await c.delete(f"/api/v1/t/{tid}/connections/{cid}")
        finally:
            release.set()
            r = await asyncio.wait_for(verify, 10)
        actions = [e["action"] for e in (await c.get(f"/api/v1/t/{tid}/audit")).json()]
    assert deleted.status_code == 204
    assert r.status_code == 404 and r.json() == {"error": "not_found"}
    assert actions[0] == "connection.verify_discarded"


async def test_a_connection_shows_its_current_cooldowns(app, owner_sessionmaker, api_settings) -> None:
    """Each quota scope's current cooldown (plugins-3 D10): a live value, the scope's kind only, never its key."""
    from datetime import UTC, datetime, timedelta

    from dewpoint.core.connections.service import _KeyringSealer
    from dewpoint.core.crypto.kek import KekSet
    from dewpoint.core.crypto.keyring import Keyring
    from dewpoint.core.db import tenant_scope
    from dewpoint.core.ratelimit.scopes import credential_hasher, scope_key

    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).json()["id"]
        assert (await c.get(f"/api/v1/t/{tid}/connections/{cid}")).json()["cooldowns"] == []
        tenant = tid if isinstance(tid, uuid.UUID) else uuid.UUID(tid)
        async with owner_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            keyring = Keyring(KekSet.from_settings(api_settings))
            key = await scope_key(s, _KeyringSealer(s, keyring), tenant, create=True)  # as a worker makes it
            assert key is not None
            hasher = credential_hasher(key)
            insert = text(
                "insert into rate_buckets (tenant_id, scope, capacity, refill_per_s, tokens, refilled_at, "
                "blocked_until) values (:t, :s, 50, 1.25, 50, now(), now() + make_interval(secs => :w))"
            )
            await s.execute(insert, {"t": tid, "s": f"mist.org:emea_01:{ORG}", "w": 120})
            await s.execute(insert, {"t": tid, "s": f"mist.token:{hasher(BODY['secret']['api_token'])}", "w": 600})
            await s.execute(insert, {"t": tid, "s": "mist.org:emea_01:someone-else", "w": 600})
        r = await c.get(f"/api/v1/t/{tid}/connections/{cid}")
    shown = {x["scope"]: datetime.fromisoformat(x["until"]) - datetime.now(UTC) for x in r.json()["cooldowns"]}
    assert set(shown) == {"mist.org", "mist.token"}
    assert timedelta(seconds=100) < shown["mist.org"] <= timedelta(seconds=125)
    assert timedelta(seconds=580) < shown["mist.token"] <= timedelta(seconds=605)
    assert "tok_" not in r.text and "someone-else" not in r.text
