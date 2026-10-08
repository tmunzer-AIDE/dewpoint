# SPDX-License-Identifier: Apache-2.0
"""Audit pruning (engine 2b spec §10.2; ruling D5): past the platform's audit retention, a scope's oldest entries are
deleted through a checkpoint, the last entry pruned, anchored first; the verifier starts each chain from its checkpoint.
Only `audit_prune()` deletes, and only through an anchored checkpoint that matches its entry. Until an off-host anchor
sink exists (#3, 2b-4b), it refuses outside a development deployment."""

import hashlib
import uuid
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, verify_anchors
from dewpoint.core.audit.prune import PruningDisabledError, prune
from dewpoint.core.audit.service import record, verify_chain
from dewpoint.core.db import tenant_scope
from dewpoint.core.platform.service import PRODUCTION, record_environment

DAYS = 400
CANONICAL = text(
    "select audit_canonical(seq, scope, actor_id, action, target_type, target_id, details, created_at) "
    "from audit_log where seq = :q"
)


async def _entries(api: Any, tenant: uuid.UUID, n: int) -> None:
    async with api() as s, s.begin():
        await tenant_scope(s, tenant)
        for i in range(n):
            await record(s, tenant_id=tenant, actor_id=None, action="member.add", target_id=str(i))


async def _backdate(owner: Any, scope: str, through: int, days: int) -> None:
    """The scope's first `through` entries made `days` older, their chain recomputed (as a privileged rewrite would)."""
    async with owner() as s, s.begin():
        await s.execute(text("SET LOCAL session_replication_role = replica"))
        seqs = (
            await s.execute(text("select seq from audit_log where scope = :s order by seq"), {"s": scope})
        ).scalars()
        prev = bytes(32)
        for k, seq in enumerate(list(seqs)):
            if k < through:
                await s.execute(text("update audit_log set created_at = created_at - make_interval(days => :d) "
                                     "where seq = :q"), {"d": days, "q": seq})  # fmt: skip
            canon = (await s.execute(CANONICAL, {"q": seq})).scalar_one()
            digest = hashlib.sha256(prev + canon.encode()).digest()
            await s.execute(text("update audit_log set prev_hash = :p, hash = :h where seq = :q"),
                            {"p": prev, "h": digest, "q": seq})  # fmt: skip
            prev = digest


@pytest.fixture
async def aged(tmp_path, api_sessionmaker, owner_sessionmaker, auditor_sessionmaker) -> dict[str, Any]:
    """A tenant scope of 5 entries, the first 3 older than the audit retention, all anchored."""
    tenant, key = uuid.uuid4(), Ed25519PrivateKey.generate()
    await _entries(api_sessionmaker, tenant, 5)
    await _backdate(owner_sessionmaker, str(tenant), 3, DAYS + 1)
    sink = FileAnchorSink(tmp_path / "anchors.jsonl", key)
    async with auditor_sessionmaker() as s, s.begin():
        await anchor_all(s, sink)
    return {"tenant": tenant, "scope": str(tenant), "key": key, "sink": sink}


async def _seqs(owner: Any, scope: str) -> list[int]:
    async with owner() as s:
        return list((await s.execute(text("select seq from audit_log where scope = :s order by seq"),
                                     {"s": scope})).scalars())  # fmt: skip


@pytest.mark.usefixtures("development_deployment")
async def test_entries_past_the_retention_go_through_an_anchored_checkpoint_and_the_chain_still_verifies(
    aged, owner_sessionmaker, auditor_sessionmaker, api_sessionmaker
) -> None:
    before = await _seqs(owner_sessionmaker, aged["scope"])
    async with auditor_sessionmaker() as s, s.begin():
        assert await prune(s, aged["sink"], older_than_days=DAYS) == {aged["scope"]: 3}
    assert await _seqs(owner_sessionmaker, aged["scope"]) == before[3:]
    checkpoint = [e for e in aged["sink"].entries() if e["seq"] == before[2]]
    assert checkpoint, "the last entry pruned is anchored off the database"
    await _entries(api_sessionmaker, aged["tenant"], 1)  # the chain goes on from what's left
    async with auditor_sessionmaker() as s, s.begin():
        await anchor_all(s, aged["sink"])
    async with auditor_sessionmaker() as s:
        assert (await verify_chain(s, aged["scope"])).ok
        assert await verify_anchors(s, aged["sink"].entries(), aged["key"].public_key()) == []
    async with auditor_sessionmaker() as s, s.begin():  # nothing more is old enough
        assert await prune(s, aged["sink"], older_than_days=DAYS) == {}


@pytest.mark.usefixtures("development_deployment")
async def test_a_checkpoint_missing_from_the_anchor_sink_is_a_problem(aged, auditor_sessionmaker) -> None:
    """The checkpoint row is in the database, which a privileged operator could rewrite: the signed sink decides."""
    async with auditor_sessionmaker() as s, s.begin():
        await prune(s, aged["sink"], older_than_days=DAYS)
    elsewhere = aged["sink"].entries()[:-1]  # every anchor but the checkpoint, the last one written
    async with auditor_sessionmaker() as s:
        problems = await verify_anchors(s, elsewhere, aged["key"].public_key())
    assert any("checkpoint" in p for p in problems), problems


@pytest.mark.usefixtures("development_deployment")
async def test_the_checkpoint_a_chain_starts_from_must_be_among_the_anchors(
    aged, owner_sessionmaker, auditor_sessionmaker
) -> None:
    """The fix-pass review's R8: a later checkpoint recorded without pruning through it isn't where verification starts
    (M4); the one it starts from, the last entry pruned, must be signed whatever a later one says."""
    before = await _seqs(owner_sessionmaker, aged["scope"])
    async with auditor_sessionmaker() as s, s.begin():
        await prune(s, aged["sink"], older_than_days=DAYS)
    async with owner_sessionmaker() as s:
        head = (await s.execute(text("select hash from audit_log where seq = :q"), {"q": before[4]})).scalar_one()
    async with auditor_sessionmaker() as s, s.begin():  # the anchored head, recorded as a checkpoint, nothing pruned
        await s.execute(text("insert into audit_checkpoints (scope, seq, hash, sink, sink_ref) "
                             "values (:s, :q, :h, 'file', 'r')"),
                        {"s": aged["scope"], "q": before[4], "h": head})  # fmt: skip
    unsigned_start = [e for e in aged["sink"].entries() if e["seq"] != before[2]]
    async with auditor_sessionmaker() as s:
        problems = await verify_anchors(s, unsigned_start, aged["key"].public_key())
    assert f"{aged['scope']}:{before[2]}: checkpoint not among the external anchors" in problems, problems


@pytest.mark.usefixtures("development_deployment")
async def test_pruning_past_a_checkpoint_breaks_the_chain(aged, owner_sessionmaker, auditor_sessionmaker) -> None:
    async with auditor_sessionmaker() as s, s.begin():
        await prune(s, aged["sink"], older_than_days=DAYS)
    async with owner_sessionmaker() as s, s.begin():  # one more entry gone without a checkpoint
        await s.execute(text("SET LOCAL session_replication_role = replica"))
        await s.execute(text("delete from audit_log where seq = (select min(seq) from audit_log where scope = :s)"),
                        {"s": aged["scope"]})  # fmt: skip
    async with auditor_sessionmaker() as s:
        assert not (await verify_chain(s, aged["scope"])).ok


@pytest.mark.usefixtures("development_deployment")
@pytest.mark.parametrize("wrong", ["no_checkpoint", "checkpoint_hash", "too_recent", "below_floor"])
async def test_audit_prune_deletes_only_through_an_anchored_checkpoint_of_an_old_enough_entry(
    aged, auditor_sessionmaker, owner_sessionmaker, wrong: str
) -> None:
    seqs = await _seqs(owner_sessionmaker, aged["scope"])
    through, days = seqs[2], DAYS
    async with auditor_sessionmaker() as s, s.begin():
        row = (await s.execute(text("select hash from audit_log where seq = :q"), {"q": seqs[4] if wrong ==
                                    "too_recent" else through})).scalar_one()  # fmt: skip
        if wrong == "too_recent":
            through = seqs[4]
        if wrong != "no_checkpoint":
            await s.execute(text("insert into audit_checkpoints (scope, seq, hash, sink, sink_ref) values "
                                 "(:s, :q, :h, 'file', 'test')"),
                            {"s": aged["scope"], "q": through,
                             "h": b"\x00" * 32 if wrong == "checkpoint_hash" else bytes(row)})  # fmt: skip
        if wrong == "below_floor":
            days = 29
    with pytest.raises(DBAPIError):
        async with auditor_sessionmaker() as s, s.begin():
            await s.execute(text("select audit_prune(:s, :q, :d)"), {"s": aged["scope"], "q": through, "d": days})
    assert await _seqs(owner_sessionmaker, aged["scope"]) == seqs


async def test_audit_pruning_is_refused_in_production_until_an_off_host_sink(aged, owner_sessionmaker,
                                                                             auditor_sessionmaker) -> None:  # fmt: skip
    """Ruling D5: disabled in production until #3's sink is configured; 2b-4a has no such sink."""
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=PRODUCTION, namespace="default")
    seqs = await _seqs(owner_sessionmaker, aged["scope"])
    entries = len(aged["sink"].entries())
    with pytest.raises(PruningDisabledError):
        async with auditor_sessionmaker() as s, s.begin():
            await prune(s, aged["sink"], older_than_days=DAYS)
    assert len(aged["sink"].entries()) == entries  # nothing anchored either
    with pytest.raises(DBAPIError, match="disabled"):  # nor does the function itself prune
        async with auditor_sessionmaker() as s, s.begin():
            await s.execute(text("select audit_prune(:s, :q, :d)"), {"s": aged["scope"], "q": seqs[2], "d": DAYS})
    assert await _seqs(owner_sessionmaker, aged["scope"]) == seqs


async def test_nothing_else_deletes_audit_entries(api_sessionmaker, owner_sessionmaker, auditor_sessionmaker) -> None:
    """The append-only trigger still refuses the table owner's own delete; no other role may delete at all, pruning's
    flag set or not."""
    tenant = uuid.uuid4()
    await _entries(api_sessionmaker, tenant, 1)
    with pytest.raises(DBAPIError, match="append-only"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("delete from audit_log where scope = :s"), {"s": str(tenant)})
    for role in (auditor_sessionmaker, api_sessionmaker):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with role() as s, s.begin():
                await s.execute(text("select set_config('dewpoint.audit_pruning', 'on', true)"))
                await s.execute(text("delete from audit_log where scope = :s"), {"s": str(tenant)})


@pytest.mark.usefixtures("development_deployment")
async def test_a_scope_pruned_whole_goes_on_from_its_checkpoint(tmp_path, api_sessionmaker, owner_sessionmaker,
                                                                auditor_sessionmaker) -> None:  # fmt: skip
    """The owner's M2 review: once every entry of a scope is pruned, the next entry chains to the checkpoint, the last
    entry pruned, not to the zero hash, so the chain still verifies from it."""
    tenant, key = uuid.uuid4(), Ed25519PrivateKey.generate()
    sink = FileAnchorSink(tmp_path / "anchors.jsonl", key)
    await _entries(api_sessionmaker, tenant, 3)
    await _backdate(owner_sessionmaker, str(tenant), 3, DAYS + 1)
    async with auditor_sessionmaker() as s, s.begin():
        await anchor_all(s, sink)
        assert await prune(s, sink, older_than_days=DAYS) == {str(tenant): 3}
    assert await _seqs(owner_sessionmaker, str(tenant)) == []
    await _entries(api_sessionmaker, tenant, 2)
    async with auditor_sessionmaker() as s, s.begin():
        await anchor_all(s, sink)
    async with auditor_sessionmaker() as s:
        assert (await verify_chain(s, str(tenant))).ok
        assert await verify_anchors(s, sink.entries(), key.public_key()) == []
