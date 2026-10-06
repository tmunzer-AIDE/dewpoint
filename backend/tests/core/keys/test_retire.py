# SPDX-License-Identifier: Apache-2.0
"""Retiring a data-key version (engine 2b spec §6.4): only when nothing needs it. It isn't the active one; its payload
floor has passed (its successor's creation + the key cache's 5 minutes + twice the longest maximum run duration ever
recorded + the namespace's retention); no run that could hold a payload under it is open; no stored record names it;
no request's or upload's digest was made with it; every live schedule's Temporal action is synced under the active
version, and every deleted one's absence settled. Each check names what it found, never a value. Retiring deletes the
version, audited."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.core.auth.users import create_user
from dewpoint.core.crypto import retire
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import tenant_scope
from tests.support.workflows import seed_workflow

RETENTION = timedelta(days=1)  # the namespace's, as Temporal reports it


@pytest.fixture
def keyring(api_settings) -> Keyring:
    return Keyring(KekSet.from_settings(api_settings))


async def _sql(owner: Any, sql: str, **params: Any) -> None:
    async with owner() as s, s.begin():
        await s.execute(text(sql), params)


@pytest.fixture
async def rotated(owner_sessionmaker, admin_sessionmaker, keyring) -> dict[str, Any]:
    """A tenant whose key 1 was succeeded by 2 four days ago, with a 1-day maximum run duration recorded: past the
    floor (4 days > 5 minutes + 2 days + 1 day), and nothing else needing 1."""
    t, w, v = await seed_workflow(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        user = (await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42")).id
    async with admin_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        await keyring.ensure_key(s, t)
        await keyring.rotate(s, t)
    await _sql(owner_sessionmaker, "update data_keys set created_at = now() - interval '4 days' where tenant_id = :t "
               "and version = 2", t=t)  # fmt: skip
    await _sql(owner_sessionmaker, "insert into run_duration_limits (days) values (1)")
    return {"t": t, "w": w, "v": v, "u": user}


async def _checks(admin: Any, tenant: uuid.UUID | None, version: int,
                  retention: timedelta | None = RETENTION) -> dict[str, bool]:  # fmt: skip
    async with admin() as s, s.begin():
        await tenant_scope(s, tenant)
        return {c.name: c.ok for c in await retire.checks(s, tenant, version, namespace_retention=retention)}


async def test_a_version_nothing_needs_retires_audited(rotated, owner_sessionmaker, admin_sessionmaker) -> None:
    t = rotated["t"]
    assert all((await _checks(admin_sessionmaker, t, 1)).values())
    async with admin_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        done = await retire.retire(s, t, 1, namespace_retention=RETENTION)
    assert all(c.ok for c in done)
    async with owner_sessionmaker() as s:
        versions = list(
            (await s.execute(text("select version from data_keys where tenant_id = :t"), {"t": t})).scalars()
        )
        audited = (await s.execute(text("select details from audit_log where action = 'keys.retire' "
                                        "and tenant_id = :t"),
                                   {"t": t})).scalars().all()  # fmt: skip
    assert versions == [2] and audited == [{"version": 1}]


async def test_the_active_version_never_retires(rotated, owner_sessionmaker, admin_sessionmaker) -> None:
    assert (await _checks(admin_sessionmaker, rotated["t"], 2))["not_active"] is False


@pytest.mark.parametrize("blocker", ["payload_floor", "no_run_duration", "no_namespace_retention", "open_runs",
                                     "records", "digests", "schedule_actions", "tombstones"])  # fmt: skip
async def test_a_version_something_still_needs_doesnt_retire(rotated, owner_sessionmaker, admin_sessionmaker,
                                                             keyring, blocker: str) -> None:  # fmt: skip
    t, w, v, u = rotated["t"], rotated["w"], rotated["v"], rotated["u"]
    retention: timedelta | None = RETENTION
    check = {"no_run_duration": "payload_floor", "no_namespace_retention": "payload_floor",
             "tombstones": "schedule_actions"}.get(blocker, blocker)  # fmt: skip
    if blocker == "payload_floor":  # its successor is only 2 days old: 5 minutes + 2 days + 1 day haven't passed
        await _sql(owner_sessionmaker, "update data_keys set created_at = now() - interval '2 days' "
                   "where tenant_id = :t and version = 2", t=t)  # fmt: skip
    elif blocker == "no_run_duration":
        await _sql(owner_sessionmaker, "delete from run_duration_limits")
    elif blocker == "no_namespace_retention":
        retention = None
    elif blocker == "open_runs":  # started before its successor's cache expired: it may hold payloads under 1
        await _sql(owner_sessionmaker, "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, "
                   "status, queued_at) values (gen_random_uuid(), :t, :w, :v, 'live', 'running', "
                   "now() - interval '5 days')",
                   t=t, w=w, v=v)  # fmt: skip
    elif blocker == "records":
        async with admin_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            blob = await keyring.encrypt(s, tenant_id=t, purpose="claim", context="x", plaintext=b"p")
        old = b"\x01" + (1).to_bytes(4, "big") + blob[5:]  # a claim naming version 1, as one sealed before would
        await _sql(owner_sessionmaker, "insert into run_inputs (id, tenant_id, owner_run_id, root_run_id, "
                   "sensitive_pointers, ciphertext, role, pointer) values (gen_random_uuid(), :t, :r, :r, '[]', :c, "
                   "'claim', '/x')", t=t, r=uuid.uuid4(), c=old)  # fmt: skip
    elif blocker == "digests":
        await _sql(owner_sessionmaker, "insert into run_requests (id, tenant_id, workflow_id, source, mode, "
                   "idempotency_key, digest, digest_key_version, status, reason, ended_at) values (gen_random_uuid(), "
                   ":t, :w, 'manual', 'live', 'k', :d, 1, 'refused', 'r', now())",
                   t=t, w=w, d=b"\x00" * 32)  # fmt: skip
    elif blocker in ("schedule_actions", "tombstones"):
        deleted = blocker == "tombstones"
        await _sql(owner_sessionmaker, "insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, "
                   "created_by, generation, synced_generation, action_key_version, deleted_at) values "
                   "(gen_random_uuid(), :t, :w, 60, 'live', :i, :u, 2, :synced, :a, case when :d then now() end)",
                   t=t, w=w, u=u, i=None if deleted else b"\x01", synced=1 if deleted else 2, a=None if deleted else 1,
                   d=deleted)  # fmt: skip
    found = await _checks(admin_sessionmaker, t, 1, retention)
    assert found[check] is False and all(ok for name, ok in found.items() if name != check), found
    with pytest.raises(retire.NotRetiredError):
        async with admin_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            await retire.retire(s, t, 1, namespace_retention=retention)
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from data_keys where tenant_id = :t"), {"t": t})).scalar() == 2


async def test_a_platform_key_version_retires_once_no_totp_secret_names_it(owner_sessionmaker, admin_sessionmaker,
                                                                           keyring) -> None:  # fmt: skip
    """The platform key seals no payload: only its records matter."""
    async with owner_sessionmaker() as s, s.begin():
        user = (await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42")).id
    async with admin_sessionmaker() as s, s.begin():
        secret = await keyring.encrypt(s, tenant_id=None, purpose="user.totp", context=str(user), plaintext=b"t")
        await keyring.rotate(s, None)
    await _sql(owner_sessionmaker, "insert into user_mfa (user_id, totp_secret_ct) values (:u, :s)", u=user, s=secret)
    assert await _checks(admin_sessionmaker, None, 1, None) == {"not_active": True, "records": False}
    await _sql(owner_sessionmaker, "delete from user_mfa where user_id = :u", u=user)
    assert await _checks(admin_sessionmaker, None, 1, None) == {"not_active": True, "records": True}
