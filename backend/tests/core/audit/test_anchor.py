# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text

from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, verify_anchors
from dewpoint.core.audit.service import record, verify_chain
from dewpoint.core.db import tenant_scope


async def test_anchor_detects_full_chain_rewrite(
    tmp_path, api_sessionmaker, owner_sessionmaker, auditor_sessionmaker
) -> None:
    key, t = Ed25519PrivateKey.generate(), uuid.uuid4()
    sink = FileAnchorSink(tmp_path / "anchors.jsonl", key)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="member.add", target_id="a")
        await record(s, tenant_id=None, actor_id=None, action="auth.login")
    # anchoring runs as the narrow auditor role, exactly like production
    async with auditor_sessionmaker() as s, s.begin():
        assert await anchor_all(s, sink) == 2  # the tenant scope and the platform scope
        assert await anchor_all(s, sink) == 0  # idempotent: heads unchanged
    async with auditor_sessionmaker() as s:
        assert await verify_anchors(s, sink.entries(), key.public_key(), max_lag=timedelta(0)) == []
    # privileged rewrite: change the row AND correctly recompute its hash, so the chain itself verifies
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("SET LOCAL session_replication_role = replica"))
        await s.execute(text("update audit_log set target_id='z' where scope <> 'platform'"))
        await s.execute(
            text(
                "update audit_log set hash = sha256(prev_hash || convert_to(audit_canonical(seq, scope, actor_id,"
                " action, target_type, target_id, details, created_at), 'UTF8')) where scope <> 'platform'"
            )
        )
    async with auditor_sessionmaker() as s:
        assert (await verify_chain(s, str(t))).ok  # the in-database chain alone cannot detect this
        problems = await verify_anchors(s, sink.entries(), key.public_key())
    assert any("hash mismatch with external anchor" in p for p in problems)


async def test_verification_fails_closed(tmp_path, api_sessionmaker, auditor_sessionmaker) -> None:
    key, t = Ed25519PrivateKey.generate(), uuid.uuid4()
    sink = FileAnchorSink(tmp_path / "anchors.jsonl", key)
    async with auditor_sessionmaker() as s:
        assert "no external anchors found" in await verify_anchors(s, [], key.public_key())
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="member.add")
    async with auditor_sessionmaker() as s, s.begin():
        await anchor_all(s, sink)
    async with api_sessionmaker() as s, s.begin():  # a new row after the last anchor
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="member.remove")
    async with auditor_sessionmaker() as s:
        assert await verify_anchors(s, sink.entries(), key.public_key()) == []  # within max_lag: fine
        lagging = await verify_anchors(s, sink.entries(), key.public_key(), max_lag=timedelta(0))
    assert any("not anchored" in p for p in lagging)


async def test_auditor_role_is_narrow(auditor_sessionmaker) -> None:
    import pytest
    from sqlalchemy.exc import DBAPIError

    for stmt in (
        "select 1 from users",
        "select 1 from connections",
        "select 1 from data_keys",
        "insert into audit_log(scope,action,prev_hash,hash,created_at) values ('x','y','\\x00','\\x00',now())",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with auditor_sessionmaker() as s, s.begin():
                await s.execute(text(stmt))
