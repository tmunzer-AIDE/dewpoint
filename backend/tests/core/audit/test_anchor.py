# SPDX-License-Identifier: Apache-2.0
import asyncio
import uuid
from datetime import UTC, datetime, timedelta, tzinfo

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text

from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, anchor_freshness, verify_anchors
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


@pytest.mark.parametrize("skew", [timedelta(hours=-2), timedelta(hours=2)])
async def test_lag_is_judged_on_the_database_clock(
    skew: timedelta, monkeypatch: pytest.MonkeyPatch, tmp_path, api_sessionmaker, auditor_sessionmaker
) -> None:
    # created_at comes from the database's clock, so the verifier's own clock must not move the window:
    # a database clock only milliseconds ahead of the verifier's used to hide a just-written row at max_lag=0
    class SkewedClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "SkewedClock":
            return super().now(tz) + skew

    monkeypatch.setattr("dewpoint.core.audit.anchor.datetime", SkewedClock)
    key, t = Ed25519PrivateKey.generate(), uuid.uuid4()
    sink = FileAnchorSink(tmp_path / "anchors.jsonl", key)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="member.add")
    async with auditor_sessionmaker() as s, s.begin():
        await anchor_all(s, sink)
    async with api_sessionmaker() as s, s.begin():  # a new row after the last anchor
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="member.remove")
    async with auditor_sessionmaker() as s:
        lagging = await verify_anchors(s, sink.entries(), key.public_key(), max_lag=timedelta(0))
        assert any("not anchored" in p for p in lagging)
        assert await verify_anchors(s, sink.entries(), key.public_key(), max_lag=timedelta(hours=1)) == []
        assert len(await anchor_freshness(s, timedelta(0))) == 1
        assert await anchor_freshness(s, timedelta(hours=1)) == []
        # an explicit `now` still overrides the database's clock: as of 2000, nothing is due yet
        assert await anchor_freshness(s, timedelta(0), now=datetime(2000, 1, 1, tzinfo=UTC)) == []


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


async def test_anchor_freshness_flags_unanchored_rows(tmp_path, api_sessionmaker, auditor_sessionmaker) -> None:
    from dewpoint.core.audit.anchor import anchor_freshness

    key, t = Ed25519PrivateKey.generate(), uuid.uuid4()
    sink = FileAnchorSink(tmp_path / "anchors.jsonl", key)
    async with auditor_sessionmaker() as s:
        assert await anchor_freshness(s, timedelta(0)) == []  # nothing to anchor yet
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="member.add")
    async with auditor_sessionmaker() as s:
        stale = await anchor_freshness(s, timedelta(0))
    assert len(stale) == 1 and stale[0].startswith(str(t))
    async with auditor_sessionmaker() as s, s.begin():
        await anchor_all(s, sink)
    async with auditor_sessionmaker() as s:
        assert await anchor_freshness(s, timedelta(0)) == []
    async with api_sessionmaker() as s, s.begin():  # a newer row is fine until it is older than max_age
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="member.remove")
    async with auditor_sessionmaker() as s:
        assert await anchor_freshness(s, timedelta(hours=1)) == []
        assert len(await anchor_freshness(s, timedelta(0))) == 1


async def test_an_anchor_signs_no_row_its_synchronous_standby_lacks(
    tmp_path, pg_url, owner_sessionmaker, auditor_sessionmaker
) -> None:  # fmt: skip
    """The review of the 2b-4b M1 checkpoint 6: a row committed locally (the inventory cutover's audit entry, its commit
    waiting for no standby) is visible before a synchronous standby holds it. An anchor that signed it, then lost it in
    a failover, would leave `audit verify` failing for good (the sink is append-only). With a standby named that never
    answers, the anchor writes nothing until it holds every row read; then it anchors them."""
    from tests.support.standby import silent_standby

    sink = FileAnchorSink(tmp_path / "anchors.jsonl", Ed25519PrivateKey.generate())
    url = pg_url.replace("postgresql+asyncpg://", "postgresql://")
    async with silent_standby(url):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("SELECT set_config('synchronous_commit', 'local', true)"))
            await record(s, tenant_id=None, actor_id=None, action="schedules.inventory_cutover")
        async with owner_sessionmaker() as s:
            seq = (await s.execute(text("select max(seq) from audit_log where scope = 'platform'"))).scalar_one()

        async def anchoring() -> int:
            async with auditor_sessionmaker() as s, s.begin():
                return await anchor_all(s, sink)

        anchored = asyncio.create_task(anchoring())
        await asyncio.sleep(1.0)
        signed_meanwhile = [e for e in sink.entries() if e["scope"] == "platform" and e["seq"] == seq]
    assert await asyncio.wait_for(anchored, 30) >= 1
    assert signed_meanwhile == []
    assert [e for e in sink.entries() if e["scope"] == "platform" and e["seq"] == seq]
