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


async def test_a_run_cut_before_its_commit_is_written_again_and_still_verifies(
    tmp_path, api_sessionmaker, auditor_sessionmaker
) -> None:
    """Compose's SIGKILL at the end of the anchor job's grace can cut a run after the file's write and before its
    transaction commits: the database records nothing, so the next run signs the same head again. The file then holds
    two signed lines for it, and verification accepts both (the S3 sink refuses the second: test_s3_anchors)."""
    key = Ed25519PrivateKey.generate()
    sink = FileAnchorSink(tmp_path / "anchors.jsonl", key)
    async with api_sessionmaker() as s, s.begin():
        await record(s, tenant_id=None, actor_id=None, action="auth.login")
    async with auditor_sessionmaker() as s:  # the cut: written to the file, never committed
        assert await anchor_all(s, sink) == 1
        await s.rollback()
    async with auditor_sessionmaker() as s, s.begin():
        assert await anchor_all(s, sink) == 1  # the same head, signed again
    first, second = sink.entries()
    assert (first["scope"], first["seq"]) == (second["scope"], second["seq"]) == ("platform", first["seq"])
    async with auditor_sessionmaker() as s:
        assert await verify_anchors(s, sink.entries(), key.public_key(), max_lag=timedelta(0)) == []
        assert await anchor_freshness(s, timedelta(0)) == []


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


async def test_anchors_verify_by_their_key_ids_across_a_rotation(api_sessionmaker, auditor_sessionmaker) -> None:
    """D6: each anchor names its key's id, signed into it; verifying keeps every id's public key (rotation), and an
    anchor whose id isn't known, or whose id was swapped, fails."""
    from dewpoint.core.audit.s3 import S3AnchorSink, read_anchors
    from tests.core.audit.fake_s3 import FakeS3

    old, new, bucket = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate(), FakeS3()
    for key, kid in ((old, "audit-1"), (new, "audit-2")):
        async with api_sessionmaker() as s, s.begin():
            await record(s, tenant_id=None, actor_id=None, action="auth.login")
        async with auditor_sessionmaker() as s, s.begin():
            assert await anchor_all(s, S3AnchorSink(bucket, "b", "p/", key, kid)) == 1  # type: ignore[arg-type]
    entries = read_anchors(bucket, "b", "p/", kept=timedelta(days=435)).entries  # type: ignore[arg-type]
    both = {"audit-1": old.public_key(), "audit-2": new.public_key()}
    async with auditor_sessionmaker() as s:
        assert await verify_anchors(s, entries, both, max_lag=timedelta(0)) == []
        rotated_away = await verify_anchors(s, entries, {"audit-2": new.public_key()}, max_lag=timedelta(0))
        assert "platform:1: anchor signed with an unknown key (audit-1)" in rotated_away
        wrong = await verify_anchors(s, entries, {"audit-1": new.public_key(), "audit-2": new.public_key()},
                                     max_lag=timedelta(0))  # fmt: skip
        assert "platform:1: bad anchor signature" in wrong
        # the id is signed: relabelled, even to an id under the same key, the anchor fails
        swapped = [dict(e, kid="audit-2") if e["seq"] == 1 else e for e in entries]
        same = {"audit-1": old.public_key(), "audit-2": old.public_key()}
        assert "platform:1: bad anchor signature" in await verify_anchors(s, swapped, same, max_lag=timedelta(0))
