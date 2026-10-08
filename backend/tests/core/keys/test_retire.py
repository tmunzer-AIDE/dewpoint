# SPDX-License-Identifier: Apache-2.0
"""Retiring a data-key version (engine 2b spec §6.4): only when nothing needs it. It isn't the active one; its payload
floor has passed (its successor's creation + the key cache's 5 minutes + twice the longest maximum run duration ever
recorded + the namespace's retention); no run that could hold a payload under it is open; no stored record names it;
no request's or upload's digest was made with it; every schedule is synced, and no live schedule's Temporal action
still carries a payload sealed under it; it was made after the tick cutover (the owner's M3 ruling: a tick from
before it may have sealed under any version that existed then, and nothing proves those histories gone); and every
run execution that could hold it is proven gone from Temporal (`run_histories`, the proof `apps.dispatcher.evidence`
makes; `test_run_evidence.py`). Each check names what it found, never a value. Retiring deletes the version,
audited."""

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
    """A tenant whose key 1 was succeeded by 2 nine days ago, with a 1-day maximum run duration recorded: past the
    floor (9 days > 5 minutes + 2 days + 1 day), and nothing else needing 1. The database was migrated empty, so its
    tick cutover predates every key here."""
    t, w, v = await seed_workflow(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        user = (await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42")).id
    async with admin_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        await keyring.ensure_key(s, t)
        await keyring.rotate(s, t)
    await _sql(owner_sessionmaker, "update data_keys set created_at = now() - interval '9 days' where tenant_id = :t "
               "and version = 2", t=t)  # fmt: skip
    await _sql(owner_sessionmaker, "insert into run_duration_limits (days) values (1)")
    return {"t": t, "w": w, "v": v, "u": user}


PROVEN = retire.RunProof()  # every run execution that could hold it shown gone


async def _checks(admin: Any, tenant: uuid.UUID | None, version: int, retention: timedelta | None = RETENTION,
                  run_histories: retire.RunProof | None = PROVEN) -> dict[str, bool]:  # fmt: skip
    async with admin() as s, s.begin():
        await tenant_scope(s, tenant)
        found = await retire.checks(s, tenant, version, namespace_retention=retention, run_histories=run_histories)
        return {c.name: c.ok for c in found}


async def test_a_version_nothing_needs_retires_audited(rotated, owner_sessionmaker, admin_sessionmaker) -> None:
    t = rotated["t"]
    assert all((await _checks(admin_sessionmaker, t, 1)).values())
    async with admin_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        done = await retire.retire(s, t, 1, namespace_retention=RETENTION, run_histories=PROVEN)
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


SCHEDULE = (
    "insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by, generation, "
    "synced_generation, action_key_version, deleted_at) values (gen_random_uuid(), :t, :w, 60, 'live', :i, :u, 2, "
    ":synced, :a, case when :deleted then now() end)"
)


@pytest.mark.parametrize("blocker", ["payload_floor", "no_run_duration", "no_namespace_retention", "open_runs",
                                     "records", "rate_scope_key", "plugin_call", "digests", "schedule_actions",
                                     "unsynced",
                                     "tombstones",
                                     "legacy_ticks", "open_execution", "retained_history", "unread_history",
                                     "lost_history", "pending_start", "run_histories_unknown"])  # fmt: skip
async def test_a_version_something_still_needs_doesnt_retire(rotated, owner_sessionmaker, admin_sessionmaker,
                                                             keyring, blocker: str) -> None:  # fmt: skip
    t, w, v, u = rotated["t"], rotated["w"], rotated["v"], rotated["u"]
    retention: timedelta | None = RETENTION
    proof: retire.RunProof | None = {
        "open_execution": retire.RunProof(open=1), "retained_history": retire.RunProof(retained=1),
        "unread_history": retire.RunProof(unread=1), "lost_history": retire.RunProof(lost=1),
        "pending_start": retire.RunProof(pending=1),
        "run_histories_unknown": None,
    }.get(blocker, PROVEN)  # fmt: skip
    check = {"no_run_duration": "payload_floor", "no_namespace_retention": "payload_floor",
             "unsynced": "schedule_actions", "tombstones": "schedule_actions",
             "rate_scope_key": "records", "plugin_call": "records"}.get(blocker, blocker)  # fmt: skip
    if proof is not PROVEN:
        check = "run_histories"
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
                   "now() - interval '10 days')",
                   t=t, w=w, v=v)  # fmt: skip
    elif blocker == "records":
        async with admin_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            blob = await keyring.encrypt(s, tenant_id=t, purpose="claim", context="x", plaintext=b"p")
        old = b"\x01" + (1).to_bytes(4, "big") + blob[5:]  # a claim naming version 1, as one sealed before would
        await _sql(owner_sessionmaker, "insert into run_inputs (id, tenant_id, owner_run_id, root_run_id, "
                   "sensitive_pointers, ciphertext, role, pointer) values (gen_random_uuid(), :t, :r, :r, '[]', :c, "
                   "'claim', '/x')", t=t, r=uuid.uuid4(), c=old)  # fmt: skip
    elif blocker == "rate_scope_key":  # the tenant's credential scope key, sealed under 1 (plugins-3 D9)
        async with admin_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            blob = await keyring.encrypt(s, tenant_id=t, purpose="rate.scope", context=str(t), plaintext=b"k" * 32)
        old = b"\x01" + (1).to_bytes(4, "big") + blob[5:]
        await _sql(owner_sessionmaker, "insert into rate_scope_keys (tenant_id, sealed) values (:t, :c)", t=t, c=old)
    elif blocker == "plugin_call":  # a call's answer under 1 (plugins-3a-2), past its expiry: no sweeper deleted it
        async with admin_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            blob = await keyring.encrypt(s, tenant_id=t, purpose="plugin.call", context="x", plaintext=b"[]")
        old = b"\x01" + (1).to_bytes(4, "big") + blob[5:]
        await _sql(owner_sessionmaker, "insert into plugin_calls (tenant_id, kind, node_ref, field, state, expires_at, "
                   "result_ct) values (:t, 'options', 'flow.x@1', 'f', 'done', now() - interval '1 day', :c)",
                   t=t, c=old)  # fmt: skip
    elif blocker == "digests":
        await _sql(owner_sessionmaker, "insert into run_requests (id, tenant_id, workflow_id, source, mode, "
                   "idempotency_key, digest, digest_key_version, status, reason, ended_at) values (gen_random_uuid(), "
                   ":t, :w, 'manual', 'live', 'k', :d, 1, 'refused', 'r', now())",
                   t=t, w=w, d=b"\x00" * 32)  # fmt: skip
    elif blocker == "schedule_actions":  # an action synced before the tick contract, still carrying its sealed argument
        await _sql(owner_sessionmaker, SCHEDULE, t=t, w=w, u=u, i=b"\x01", synced=2, a=1, deleted=False)
    elif blocker == "unsynced":
        await _sql(owner_sessionmaker, SCHEDULE, t=t, w=w, u=u, i=b"\x01", synced=1, a=None, deleted=False)
    elif blocker == "tombstones":  # its absence not yet recorded
        await _sql(owner_sessionmaker, SCHEDULE, t=t, w=w, u=u, i=None, synced=1, a=None, deleted=True)
    elif blocker == "legacy_ticks":  # made before the tick cutover: a tick from before it may still hold it
        await _sql(owner_sessionmaker, "update data_keys set created_at = (select at from tick_cutover) - "
                   "interval '1 day' where tenant_id = :t and version = 1", t=t)  # fmt: skip
    found = await _checks(admin_sessionmaker, t, 1, retention, proof)
    assert {name for name, ok in found.items() if not ok} == {check}, found
    with pytest.raises(retire.NotRetiredError):
        async with admin_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            await retire.retire(s, t, 1, namespace_retention=retention, run_histories=proof)
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from data_keys where tenant_id = :t"), {"t": t})).scalar() == 2


async def test_a_migrated_schedule_or_one_sealed_under_another_version_needs_nothing(
    rotated, owner_sessionmaker, admin_sessionmaker
) -> None:
    t, w, u = rotated["t"], rotated["w"], rotated["u"]
    await _sql(owner_sessionmaker, SCHEDULE, t=t, w=w, u=u, i=b"\x01", synced=2, a=None, deleted=False)
    await _sql(owner_sessionmaker, SCHEDULE, t=t, w=w, u=u, i=b"\x01", synced=2, a=2, deleted=False)
    await _sql(owner_sessionmaker, SCHEDULE, t=t, w=w, u=u, i=None, synced=2, a=None, deleted=True)
    assert all((await _checks(admin_sessionmaker, t, 1)).values())


async def test_a_late_closing_legacy_tick_keeps_the_version_it_could_hold(rotated, owner_sessionmaker,
                                                                          admin_sessionmaker) -> None:  # fmt: skip
    """The owner's M3 timeline: a schedule's action moves to key 2 on day 0; a tick started before, under key 1, closes
    on day 40; the namespace keeps its history 30 days, to day 70. On day 40 every other check passes (the floor:
    5 minutes + 2 days + 30 days), and nothing in the database or Temporal can show that tick's history gone: key 1,
    made before the tick cutover, is kept. A key made after the cutover, on the same timeline, retires: no tick holds a
    payload under it."""
    t = rotated["t"]
    await _sql(owner_sessionmaker, "update data_keys set created_at = now() - interval '40 days' where tenant_id = :t "
               "and version = 2", t=t)  # fmt: skip
    await _sql(owner_sessionmaker, "update data_keys set created_at = (select at from tick_cutover) - "
               "interval '1 day' where tenant_id = :t and version = 1", t=t)  # fmt: skip
    found = await _checks(admin_sessionmaker, t, 1, timedelta(days=30))
    assert {name for name, ok in found.items() if not ok} == {"legacy_ticks"}, found
    await _sql(owner_sessionmaker, "update data_keys set created_at = (select at from tick_cutover) + "
               "interval '1 second' where tenant_id = :t and version = 1", t=t)  # fmt: skip
    assert all((await _checks(admin_sessionmaker, t, 1, timedelta(days=30))).values())


async def test_no_tenant_version_retires_before_the_tick_cutover_is_recorded(rotated, owner_sessionmaker,
                                                                             admin_sessionmaker) -> None:  # fmt: skip
    """A database that had tenants when migration 0039 ran records no cutover: until `keys tick-cutover` records one,
    after the last dispatcher from before stopped, any version may be held by a legacy tick."""
    async with owner_sessionmaker() as s:
        cutover = (await s.execute(text("select at from tick_cutover"))).scalar_one()
    await _sql(owner_sessionmaker, "delete from tick_cutover")
    try:
        assert (await _checks(admin_sessionmaker, rotated["t"], 1))["legacy_ticks"] is False
    finally:
        await _sql(owner_sessionmaker, "insert into tick_cutover (at) values (:a)", a=cutover)


async def test_a_platform_key_version_retires_once_no_totp_secret_names_it(owner_sessionmaker, admin_sessionmaker,
                                                                           keyring) -> None:  # fmt: skip
    """The platform key seals no payload, and no tick ever used it: only its records matter."""
    async with owner_sessionmaker() as s, s.begin():
        user = (await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42")).id
    async with admin_sessionmaker() as s, s.begin():
        secret = await keyring.encrypt(s, tenant_id=None, purpose="user.totp", context=str(user), plaintext=b"t")
        await keyring.rotate(s, None)
    await _sql(owner_sessionmaker, "insert into user_mfa (user_id, totp_secret_ct) values (:u, :s)", u=user, s=secret)
    assert await _checks(admin_sessionmaker, None, 1, None, None) == {"not_active": True, "records": False}
    await _sql(owner_sessionmaker, "delete from user_mfa where user_id = :u", u=user)
    assert await _checks(admin_sessionmaker, None, 1, None, None) == {"not_active": True, "records": True}
