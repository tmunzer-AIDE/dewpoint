# SPDX-License-Identifier: Apache-2.0
"""`dewpoint keys reencrypt` (engine 2b spec §6.4): every record stored under an older data-key version sealed again
under the active one, its plaintext, purpose and context unchanged, so the older version can retire. As the key admin, a
tenant at a time under its scope, in batches, each write a compare-and-swap on the blob it read: a record the
application rewrote meanwhile is never overwritten. A schedule's Temporal action is sealed again by its sync, which a
raised generation queues."""

import struct
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.core.auth.users import create_user
from dewpoint.core.crypto import reencrypt
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import tenant_scope
from dewpoint.core.ingress.keys import ensure_event_key
from tests.support.workflows import seed_workflow

# (table, key column, ciphertext column, purpose, context): what each record is sealed as.
TENANT_FIELDS = [
    ("run_inputs", "id", "ciphertext", "claim", "id"),
    ("step_outputs", "id", "ciphertext", "claim", "id"),
    ("run_secret_index", "root_run_id", "ciphertext", "secret_index", "root_run_id"),
    ("csv_uploads", "id", "staged", "csv.upload", "id"),
    ("csv_mappings", "workflow_id", "mapping", "csv.mapping", "workflow_id"),
    ("schedules", "id", "input", "schedule.input", "id"),
    ("connections", "id", "secret_ct", "connection.secret", "id"),
    ("tenant_event_keys", "version", "private_sealed", "event.private", "version"),
]


def version_of(blob: bytes) -> int:
    return int(struct.unpack(">I", bytes(blob)[1:5])[0])


@pytest.fixture
def keyring(api_settings) -> Keyring:
    return Keyring(KekSet.from_settings(api_settings))


async def _sealed(admin: Any, keyring: Keyring, tenant: uuid.UUID | None, purpose: str, context: str,
                  plaintext: bytes) -> bytes:  # fmt: skip
    async with admin() as s, s.begin():
        await tenant_scope(s, tenant)
        return await keyring.encrypt(s, tenant_id=tenant, purpose=purpose, context=context, plaintext=plaintext)


async def _sql(owner: Any, sql: str, **params: Any) -> None:
    async with owner() as s, s.begin():
        await s.execute(text(sql), params)


@pytest.fixture
async def stored(owner_sessionmaker, admin_sessionmaker, keyring) -> dict[str, Any]:
    """A tenant with one record of every kind sealed under its data key 1, a tombstone, and a user's TOTP secrets
    under the platform key 1; then both keys rotated to 2."""
    owner, admin = owner_sessionmaker, admin_sessionmaker
    t, w, v = await seed_workflow(owner)
    async with owner() as s, s.begin():
        user = (await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42")).id
    async with admin() as s, s.begin():
        await tenant_scope(s, t)
        await keyring.ensure_key(s, t)
        await ensure_event_key(s, keyring, t)
    ids = {"run_inputs": uuid.uuid4(), "step_outputs": uuid.uuid4(), "run_secret_index": uuid.uuid4(),
           "csv_uploads": uuid.uuid4(), "csv_mappings": w, "schedules": uuid.uuid4(), "connections": uuid.uuid4(),
           "tenant_event_keys": 1}  # fmt: skip
    plain = {table: f"{table}-plaintext".encode() for table in ids}

    async def seal(table: str, purpose: str) -> bytes:
        return await _sealed(admin, keyring, t, purpose, str(ids[table]), plain[table])

    root = uuid.uuid4()
    await _sql(owner, "insert into run_inputs (id, tenant_id, owner_run_id, root_run_id, sensitive_pointers, "
               "ciphertext, role, pointer) values (:i, :t, :r, :r, '[]', :c, 'claim', '/x')",
               i=ids["run_inputs"], t=t, r=root, c=await seal("run_inputs", "claim"))  # fmt: skip
    await _sql(owner, "insert into step_outputs (id, tenant_id, owner_run_id, root_run_id, sensitive_pointers, "
               "ciphertext, kind) values (:i, :t, :r, :r, '[]', :c, 'output')",
               i=ids["step_outputs"], t=t, r=root, c=await seal("step_outputs", "claim"))  # fmt: skip
    await _sql(owner, "insert into run_secret_index (root_run_id, tenant_id, version, string_count, byte_count, "
               "ciphertext) values (:i, :t, 7, 0, 0, :c)",
               i=ids["run_secret_index"], t=t, c=await seal("run_secret_index", "secret_index"))  # fmt: skip
    await _sql(owner, "insert into csv_uploads (id, tenant_id, owner_id, workflow_id, staged, file_digest, "
               "digest_key_version, size_bytes, row_count, expires_at) values (:i, :t, :u, :w, :c, :d, 1, 1, 1, "
               "now() + interval '1 hour')", i=ids["csv_uploads"], t=t, u=user, w=w, d=b"\x00" * 32,
               c=await seal("csv_uploads", "csv.upload"))  # fmt: skip
    await _sql(owner, "insert into csv_mappings (workflow_id, tenant_id, mapping, saved_by, saved_against) "
               "values (:w, :t, :c, :u, :v)", w=w, t=t, u=user, v=v,
               c=await seal("csv_mappings", "csv.mapping"))  # fmt: skip
    await _sql(owner, "insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by, "
               "generation, synced_generation) values (:i, :t, :w, 60, 'live', :c, :u, 3, 3)",
               i=ids["schedules"], t=t, w=w, u=user, c=await seal("schedules", "schedule.input"))  # fmt: skip
    tombstone = uuid.uuid4()
    await _sql(owner, "insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by, "
               "generation, synced_generation, deleted_at) values (:i, :t, :w, 60, 'live', null, :u, 4, 4, now())",
               i=tombstone, t=t, w=w, u=user)  # fmt: skip
    await _sql(owner, "insert into connections (id, tenant_id, type, name, config, secret_ct, revision, status) "
               "values (:i, :t, 'mist', 'c', '{}', :c, 5, 'verified')",
               i=ids["connections"], t=t, c=await seal("connections", "connection.secret"))  # fmt: skip
    async with owner() as s:  # the keypair's private key, as ensure_event_key sealed it
        plain["tenant_event_keys"] = await keyring.decrypt(
            s, tenant_id=t, purpose="event.private", context="1",
            blob=(await s.execute(text("select private_sealed from tenant_event_keys where tenant_id = :t"),
                                  {"t": t})).scalar_one(),
        )  # fmt: skip
    secret = await _sealed(admin, keyring, None, "user.totp", str(user), b"totp-secret")
    pending = await _sealed(admin, keyring, None, "user.totp", f"{user}:pending", b"totp-pending")
    await _sql(owner, "insert into user_mfa (user_id, totp_secret_ct, totp_pending_ct) values (:u, :s, :p)",
               u=user, s=secret, p=pending)  # fmt: skip
    async with admin() as s, s.begin():
        await tenant_scope(s, t)
        assert await keyring.rotate(s, t) == 2
        assert await keyring.rotate(s, None) == 2
    return {"t": t, "ids": ids, "plain": plain, "user": user, "tombstone": tombstone}


async def _blob(owner: Any, table: str, column: str, key: str, value: Any, tenant: uuid.UUID) -> bytes:
    async with owner() as s:
        found = await s.execute(text(f"select {column} from {table} where {key} = :k and tenant_id = :t"),  # noqa: S608
                                {"k": value, "t": tenant})  # fmt: skip
        return bytes(found.scalar_one())


async def test_every_record_under_an_older_version_is_sealed_again_under_the_active_one(
    stored, owner_sessionmaker, admin_sessionmaker, keyring
) -> None:
    t = stored["t"]
    counts = await reencrypt.tenant(admin_sessionmaker, keyring, t, batch=1)
    assert counts == {table: 1 for table, *_ in TENANT_FIELDS} | {"schedule_actions": 1}
    async with owner_sessionmaker() as s:
        for table, key, column, purpose, _ in TENANT_FIELDS:
            blob = await _blob(owner_sessionmaker, table, column, key, stored["ids"][table], t)
            assert version_of(blob) == 2, table
            opened = await keyring.decrypt(
                s, tenant_id=t, purpose=purpose, context=str(stored["ids"][table]), blob=blob
            )
            assert opened == stored["plain"][table], table
    assert await reencrypt.tenant(admin_sessionmaker, keyring, t, batch=1) == dict.fromkeys(counts, 0)


async def test_nothing_else_of_a_record_changes(stored, owner_sessionmaker, admin_sessionmaker, keyring) -> None:
    """A connection keeps its revision and verification, a secret index its content version, a tombstone its empty
    input and generation; a live schedule's generation is raised, so its sync seals its Temporal action again."""
    t = stored["t"]
    await reencrypt.tenant(admin_sessionmaker, keyring, t)
    async with owner_sessionmaker() as s:
        connection = (await s.execute(text("select revision, status from connections where id = :i"),
                                      {"i": stored["ids"]["connections"]})).one()  # fmt: skip
        index = (await s.execute(text("select version from run_secret_index where root_run_id = :i"),
                                 {"i": stored["ids"]["run_secret_index"]})).scalar_one()  # fmt: skip
        schedules = dict((await s.execute(text("select id, (generation, input is null) from schedules "
                                               "where tenant_id = :t"), {"t": t})).all())  # fmt: skip
    assert tuple(connection) == (5, "verified") and index == 7
    assert schedules == {stored["ids"]["schedules"]: (4, False), stored["tombstone"]: (4, True)}


async def test_the_platform_keys_records_are_sealed_again(stored, owner_sessionmaker, admin_sessionmaker,
                                                          keyring) -> None:  # fmt: skip
    assert await reencrypt.platform(admin_sessionmaker, keyring) == {"user_mfa": 2}
    async with owner_sessionmaker() as s:
        row = (await s.execute(text("select totp_secret_ct, totp_pending_ct from user_mfa where user_id = :u"),
                               {"u": stored["user"]})).one()  # fmt: skip
        assert [version_of(b) for b in row] == [2, 2]
        user = str(stored["user"])
        assert await keyring.decrypt(s, tenant_id=None, purpose="user.totp", context=user, blob=row[0]) == (
            b"totp-secret"
        )  # fmt: skip
        assert await keyring.decrypt(s, tenant_id=None, purpose="user.totp", context=f"{user}:pending",
                                     blob=row[1]) == b"totp-pending"  # fmt: skip
    assert await reencrypt.platform(admin_sessionmaker, keyring) == {"user_mfa": 0}


async def test_a_record_rewritten_meanwhile_is_never_overwritten(monkeypatch, stored, owner_sessionmaker,
                                                                 admin_sessionmaker, keyring) -> None:  # fmt: skip
    """The application changed a schedule's input between the read and the write: its new value stays."""
    t, sid = stored["t"], stored["ids"]["schedules"]
    fresh = await _sealed(admin_sessionmaker, keyring, t, "schedule.input", str(sid), b"changed meanwhile")

    async def rewritten(table: str) -> None:
        if table == "schedules":
            await _sql(owner_sessionmaker, "update schedules set input = :c where id = :i", c=fresh, i=sid)

    monkeypatch.setattr(reencrypt, "_after_choosing", rewritten)
    counts = await reencrypt.tenant(admin_sessionmaker, keyring, t)
    assert counts["schedules"] == 0
    assert await _blob(owner_sessionmaker, "schedules", "input", "id", sid, t) == fresh


async def test_the_key_admin_rewrites_ciphertexts_only(owner_sessionmaker) -> None:
    """Its grants on these tables: the sealed columns, and a schedule's generation to queue its sync."""
    async with owner_sessionmaker() as s:
        found = await s.execute(text(
            "select table_name, string_agg(column_name, ',' order by column_name) from "
            "information_schema.column_privileges "
            "where grantee = 'dewpoint_admin' and privilege_type = 'UPDATE' and table_name = any(:t) group by 1"),
            {"t": [table for table, *_ in TENANT_FIELDS] + ["user_mfa"]})  # fmt: skip
        updatable = dict(found.all())
    assert {k: v for k, v in updatable.items() if k not in ("connections", "user_mfa")} == {
        "run_inputs": "ciphertext", "step_outputs": "ciphertext", "run_secret_index": "ciphertext",
        "csv_uploads": "staged", "csv_mappings": "mapping", "schedules": "generation,input",
        "tenant_event_keys": "private_sealed",
    }  # fmt: skip


async def test_a_version_never_retires_under_a_batch_sealing_records_with_it(
    monkeypatch, owner_sessionmaker, admin_sessionmaker, keyring
) -> None:
    """The owner's M3 review: a batch reads the active version, then writes records sealed under it. Rotation and
    retirement wait for the batch, under the scope's key lock: otherwise a rotation could make that version old and
    a retirement delete it, unreferenced, before the batch wrote a record under it."""
    import asyncio

    from dewpoint.core.crypto import retire

    async with owner_sessionmaker() as s, s.begin():
        user = (await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42")).id
    secret = await _sealed(admin_sessionmaker, keyring, None, "user.totp", str(user), b"totp-secret")  # version 1
    await _sql(owner_sessionmaker, "insert into user_mfa (user_id, totp_secret_ct) values (:u, :s)", u=user, s=secret)
    async with admin_sessionmaker() as s, s.begin():
        assert await keyring.rotate(s, None) == 2
    chose, release = asyncio.Event(), asyncio.Event()

    async def paused(table: str) -> None:
        chose.set()
        await release.wait()

    monkeypatch.setattr(reencrypt, "_after_choosing", paused)
    sealing = asyncio.create_task(reencrypt.platform(admin_sessionmaker, keyring))  # sealing under version 2
    await asyncio.wait_for(chose.wait(), 10)

    async def rotate_and_retire_2() -> None:
        async with admin_sessionmaker() as s, s.begin():
            await keyring.rotate(s, None)  # 3 becomes active
        try:
            async with admin_sessionmaker() as s, s.begin():
                await retire.retire(s, None, 2, namespace_retention=None)
        except retire.NotRetiredError:
            pass  # once the batch wrote under 2, 2 is still needed

    lifecycle = asyncio.create_task(rotate_and_retire_2())
    try:
        done, _ = await asyncio.wait([lifecycle], timeout=1)
        assert not done, "a rotation went through while a batch was sealing under the active version"
    finally:
        release.set()
        await asyncio.wait_for(sealing, 10)
        await asyncio.wait_for(lifecycle, 10)
    async with owner_sessionmaker() as s:
        blob = (
            await s.execute(text("select totp_secret_ct from user_mfa where user_id = :u"), {"u": user})
        ).scalar_one()
        assert await keyring.decrypt(s, tenant_id=None, purpose="user.totp", context=str(user), blob=blob) == (
            b"totp-secret"
        )  # its version still exists  # fmt: skip
