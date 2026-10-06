# SPDX-License-Identifier: Apache-2.0
"""Plugin calls in the database (plugins-3 D3): the API asks and reads; a worker claims with a fresh token and a lease,
and its answer is taken only while its token, its lease and the call's expiry all hold and the API hasn't abandoned
the call. A lapsed lease can be claimed again, after which the first claimant's answer is refused."""

import asyncio
import uuid
from typing import Any

from sqlalchemy import text

from dewpoint.core.db import tenant_scope
from dewpoint.core.plugins import calls
from tests.support.connections import add_connection


async def tenant(owner: Any) -> uuid.UUID:
    tid = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into tenants (id, name, slug) values (:i, 't', :s)"), {"i": tid, "s": tid.hex[:12]}
        )
    return tid


async def ask(api: Any, tid: uuid.UUID, *, expires_s: float = 30) -> uuid.UUID:
    async with api() as s, s.begin():
        await tenant_scope(s, tid)
        return await calls.ask_options(
            s, tid, node_ref="demo.pick@1", field="site_id", connection_id=None, revision=None, query="pa",
            type_hash=None, expires_s=expires_s,
        )  # fmt: skip


async def claim(worker: Any, tid: uuid.UUID, cid: uuid.UUID, lease_s: float = 15) -> calls.Claimed | None:
    async with worker() as s, s.begin():
        await tenant_scope(s, tid)
        return await calls.claim(s, tid, cid, lease_s=lease_s)


async def answer(worker: Any, tid: uuid.UUID, cid: uuid.UUID, token: uuid.UUID, blob: bytes = b"sealed") -> bool:
    async with worker() as s, s.begin():
        await tenant_scope(s, tid)
        return await calls.answer(s, tid, cid, token, blob)


async def read(api: Any, tid: uuid.UUID, cid: uuid.UUID) -> calls.Answer | None:
    async with api() as s, s.begin():
        await tenant_scope(s, tid)
        return await calls.read(s, tid, cid)


async def test_a_claimed_call_is_answered_once(owner_sessionmaker, api_sessionmaker, worker_sessionmaker) -> None:
    tid = await tenant(owner_sessionmaker)
    cid = await ask(api_sessionmaker, tid)
    assert await read(api_sessionmaker, tid, cid) == calls.Answer("pending", None, None)
    claimed = await claim(worker_sessionmaker, tid, cid)
    assert claimed is not None
    assert (claimed.kind, claimed.node_ref, claimed.field, claimed.query) == ("options", "demo.pick@1", "site_id", "pa")
    assert await answer(worker_sessionmaker, tid, cid, claimed.token)
    assert await read(api_sessionmaker, tid, cid) == calls.Answer("done", b"sealed", None)
    assert not await answer(worker_sessionmaker, tid, cid, claimed.token, b"again")
    assert await read(api_sessionmaker, tid, cid) == calls.Answer("done", b"sealed", None)


async def test_a_refusal_is_fenced_the_same_way(owner_sessionmaker, api_sessionmaker, worker_sessionmaker) -> None:
    tid = await tenant(owner_sessionmaker)
    cid = await ask(api_sessionmaker, tid)
    claimed = await claim(worker_sessionmaker, tid, cid)
    assert claimed is not None
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tid)
        assert not await calls.refuse(s, tid, cid, uuid.uuid4(), "timeout")
        assert await calls.refuse(s, tid, cid, claimed.token, "timeout")
    assert await read(api_sessionmaker, tid, cid) == calls.Answer("failed", None, "timeout")


async def test_a_claimed_call_with_a_live_lease_isnt_claimed_again(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    tid = await tenant(owner_sessionmaker)
    cid = await ask(api_sessionmaker, tid)
    assert await claim(worker_sessionmaker, tid, cid) is not None
    assert await claim(worker_sessionmaker, tid, cid) is None


async def test_a_lapsed_lease_is_claimed_again_and_the_first_answer_refused(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    tid = await tenant(owner_sessionmaker)
    cid = await ask(api_sessionmaker, tid)
    first = await claim(worker_sessionmaker, tid, cid, lease_s=0.2)
    assert first is not None
    await asyncio.sleep(0.3)
    assert not await answer(worker_sessionmaker, tid, cid, first.token)  # its lease lapsed
    second = await claim(worker_sessionmaker, tid, cid)
    assert second is not None and second.token != first.token
    assert not await answer(worker_sessionmaker, tid, cid, first.token)
    assert await answer(worker_sessionmaker, tid, cid, second.token)


async def test_an_expired_call_is_neither_claimed_nor_answered(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    tid = await tenant(owner_sessionmaker)
    cid = await ask(api_sessionmaker, tid, expires_s=0.3)
    claimed = await claim(worker_sessionmaker, tid, cid)
    assert claimed is not None
    await asyncio.sleep(0.4)
    assert not await answer(worker_sessionmaker, tid, cid, claimed.token)
    late = await ask(api_sessionmaker, tid, expires_s=-1)
    assert await claim(worker_sessionmaker, tid, late) is None


async def test_an_abandoned_call_takes_no_answer(owner_sessionmaker, api_sessionmaker, worker_sessionmaker) -> None:
    tid = await tenant(owner_sessionmaker)
    cid = await ask(api_sessionmaker, tid)
    claimed = await claim(worker_sessionmaker, tid, cid)
    assert claimed is not None
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, tid)
        await calls.forget(s, tid, cid)
    assert not await answer(worker_sessionmaker, tid, cid, claimed.token)
    assert await read(api_sessionmaker, tid, cid) is None


async def test_a_call_being_claimed_elsewhere_is_passed_by(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    tid = await tenant(owner_sessionmaker)
    cid = await ask(api_sessionmaker, tid)
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tid)
        held = await calls.claim(s, tid, cid, lease_s=15)  # uncommitted: its row stays locked
        assert held is not None
        assert await claim(worker_sessionmaker, tid, cid) is None  # SKIP LOCKED: no wait, no claim


async def test_the_worker_finds_the_due_calls_of_its_refs_and_types(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    tid = await tenant(owner_sessionmaker)
    conn = await add_connection(owner_sessionmaker, tid, type_key="demo")
    options = await ask(api_sessionmaker, tid)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, tid)
        verify = await calls.ask_verify(s, tid, connection_type="demo", connection_id=conn, revision=1, type_hash="h")
    async with worker_sessionmaker() as s, s.begin():
        assert await calls.candidates(s, ["demo.pick@1"], ["demo"], ["h"], 10) == [(tid, options), (tid, verify)]
        assert await calls.candidates(s, ["demo.pick@1"], [], ["h"], 10) == [(tid, options)]
        assert await calls.candidates(s, [], ["demo"], ["h"], 1) == [(tid, verify)]
        assert await calls.candidates(s, [], ["demo"], ["other"], 1) == []
