# SPDX-License-Identifier: Apache-2.0
import uuid

import pytest
from sqlalchemy import text

from dewpoint.apps.plugin_loader import sync_installed
from dewpoint.plugins.mist import PLUGIN as MIST
from tests.apps.api.helpers import session_client

ORG = str(uuid.uuid4())
BODY = {
    "type": "mist",
    "name": "Acme Prod",
    "config": {"cloud": "emea_01", "org_id": ORG},
    "secret": {"api_token": "tok_" + "a" * 36},
}


@pytest.fixture(autouse=True)
async def mist_synced(owner_sessionmaker) -> None:  # type: ignore[no-untyped-def]
    """The API knows the types `dewpoint plugins sync` registered (plugins-3 D11)."""
    async with owner_sessionmaker() as s, s.begin():
        await sync_installed(s, [MIST])


async def test_connection_types_come_from_synced_manifests(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        listed = (await c.get("/api/v1/connection-types")).json()
    assert [t["key"] for t in listed] == ["mist"]
    assert listed[0]["clouds"]["emea_01"] == "api.eu.mist.com" and listed[0]["secret_fields"] == ["api_token"]


async def test_a_type_no_synced_plugin_declares_is_unknown(app, owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("delete from plugin_manifests where name = 'mist'"))
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        assert (await c.get("/api/v1/connection-types")).json() == []
        r = await c.post(f"/api/v1/t/{tid}/connections", json=BODY)
    assert r.status_code == 422 and r.json() == {"error": "unknown_type"}


async def test_an_invalid_config_names_fields_not_values(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        bad = {**BODY, "config": {"cloud": "emea_01", "org_id": ORG.upper()}, "secret": {"api_token": "short-secret"}}
        r = await c.post(f"/api/v1/t/{tid}/connections", json=bad)
    assert r.status_code == 422 and r.json() == {"error": "invalid", "fields": ["org_id"]}
    assert "short-secret" not in r.text


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


async def test_moving_a_connection_to_another_host_needs_its_secret_again(
    app, owner_sessionmaker, api_settings
) -> None:
    """The stored secret is never sent to a host the person who wrote it didn't choose (the 3a-2 review's finding 1):
    changing the field a type's host comes from needs the secret in the same request."""
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).json()["id"]
        moved = {"config": {"cloud": "global_01", "org_id": ORG}}
        refused = await c.patch(f"/api/v1/t/{tid}/connections/{cid}", json=moved)
        same_host = await c.patch(f"/api/v1/t/{tid}/connections/{cid}",
                                  json={"config": {"cloud": "emea_01", "org_id": str(uuid.uuid4())}})  # fmt: skip
        with_secret = await c.patch(f"/api/v1/t/{tid}/connections/{cid}",
                                    json={**moved, "secret": {"api_token": "tok_" + "c" * 36}})  # fmt: skip
    assert (refused.status_code, refused.json()) == (422, {"error": "secret_required"})
    assert same_host.status_code == 200
    assert with_secret.status_code == 200 and with_secret.json()["config"]["cloud"] == "global_01"


async def test_cooldowns_of_a_config_its_type_no_longer_accepts_are_unknown(
    app, owner_sessionmaker, api_settings
) -> None:
    """A stored config the synced declaration refuses (a plugin upgrade added a scope field) shows no cooldowns
    instead of failing with the decrypted secret in scope (the 3a-2 review's finding 6)."""
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).json()["id"]
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text('update connections set config = \'{"cloud": "emea_01"}\' where id = :c'), {"c": cid})
        r = await c.get(f"/api/v1/t/{tid}/connections/{cid}")
    assert r.status_code == 200 and r.json()["cooldowns"] is None
