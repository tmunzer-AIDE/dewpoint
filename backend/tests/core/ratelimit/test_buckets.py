# SPDX-License-Identifier: Apache-2.0
"""Rate buckets (plugins-3 D9, D10): a request takes a token from every scope of its connection in one transaction, or
from none; a short wait happens inside the attempt, a longer one fails `cooldown` (this attempt sent nothing); a
provider's `Retry-After` blocks a scope, never shortening an existing block, at most an hour; buckets are the
tenant's."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from dewpoint.core.db import tenant_scope
from dewpoint.core.ratelimit.buckets import CooldownError, Scope, acquire, block, current_cooldowns, take


async def tenant(owner) -> uuid.UUID:  # type: ignore[no-untyped-def]
    tid = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into tenants (id, name, slug) values (:i, 't', :s)"), {"i": tid, "s": tid.hex[:12]}
        )
    return tid


async def _take(maker, tid: uuid.UUID, scopes: list[Scope]) -> float:  # type: ignore[no-untyped-def]
    async with maker() as s, s.begin():
        await tenant_scope(s, tid)
        return await take(s, tid, scopes)


async def _tokens(maker, tid: uuid.UUID, scope: str) -> float:  # type: ignore[no-untyped-def]
    async with maker() as s, s.begin():
        await tenant_scope(s, tid)
        return (await s.execute(text("select tokens from rate_buckets where scope = :s"), {"s": scope})).scalar_one()


async def test_a_new_scope_starts_full_and_gives_a_token(owner_sessionmaker, worker_sessionmaker) -> None:
    tid = await tenant(owner_sessionmaker)
    assert await _take(worker_sessionmaker, tid, [Scope("mist.org:a", 5, 0.001)]) == 0
    assert await _tokens(worker_sessionmaker, tid, "mist.org:a") == pytest.approx(4, abs=0.01)


async def test_an_empty_scope_says_how_long_to_wait(owner_sessionmaker, worker_sessionmaker) -> None:
    tid = await tenant(owner_sessionmaker)
    scope = Scope("mist.org:a", 1, 0.5)
    assert await _take(worker_sessionmaker, tid, [scope]) == 0
    wait = await _take(worker_sessionmaker, tid, [scope])
    assert 1.0 < wait <= 2.0


async def test_tokens_refill_with_time(owner_sessionmaker, worker_sessionmaker) -> None:
    tid = await tenant(owner_sessionmaker)
    scope = Scope("mist.org:a", 1, 1000)
    assert await _take(worker_sessionmaker, tid, [scope]) == 0
    async with worker_sessionmaker() as s, s.begin():  # as if a second had passed
        await tenant_scope(s, tid)
        await s.execute(text("update rate_buckets set refilled_at = refilled_at - interval '1 second'"))
    assert await _take(worker_sessionmaker, tid, [scope]) == 0


async def test_all_scopes_or_none(owner_sessionmaker, worker_sessionmaker) -> None:
    tid = await tenant(owner_sessionmaker)
    full, empty = Scope("mist.org:a", 5, 0.001), Scope("mist.token:b", 1, 0.001)
    await _take(worker_sessionmaker, tid, [empty])
    assert await _take(worker_sessionmaker, tid, [full, empty]) > 0
    assert await _tokens(worker_sessionmaker, tid, "mist.org:a") == pytest.approx(5, abs=0.01)


async def test_acquire_waits_briefly_then_fails_cooldown(owner_sessionmaker, worker_sessionmaker) -> None:
    tid = await tenant(owner_sessionmaker)
    quick = Scope("mist.org:a", 1, 20)  # empty for 0.05 s
    await _take(worker_sessionmaker, tid, [quick])
    slept: list[float] = []
    await acquire(worker_sessionmaker, tid, [quick], max_wait_s=1, beat=lambda: slept.append(1))
    slow = Scope("mist.org:b", 1, 0.01)  # empty for 100 s
    await _take(worker_sessionmaker, tid, [slow])
    with pytest.raises(CooldownError):
        await acquire(worker_sessionmaker, tid, [slow], max_wait_s=1, beat=lambda: None)


async def test_a_block_holds_every_run_until_it_ends(owner_sessionmaker, worker_sessionmaker) -> None:
    tid = await tenant(owner_sessionmaker)
    scope = Scope("mist.org:a", 50, 1.25)
    until = datetime.now(UTC) + timedelta(seconds=60)
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tid)
        await block(s, tid, [scope], until)
    assert await _take(worker_sessionmaker, tid, [scope]) > 50
    with pytest.raises(CooldownError) as raised:
        await acquire(worker_sessionmaker, tid, [scope], max_wait_s=10, beat=lambda: None)
    assert raised.value.until is not None and abs((raised.value.until - until).total_seconds()) < 1


async def test_a_block_never_shortens_and_is_capped_at_an_hour(owner_sessionmaker, worker_sessionmaker) -> None:
    tid = await tenant(owner_sessionmaker)
    scope = Scope("mist.org:a", 50, 1.25)
    now = datetime.now(UTC)
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tid)
        await block(s, tid, [scope], now + timedelta(hours=5))
        await block(s, tid, [scope], now + timedelta(seconds=30))
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tid)
        found = await current_cooldowns(s, tid, ["mist.org:a", "mist.org:none"])
    assert set(found) == {"mist.org:a"}
    assert timedelta(minutes=59) < found["mist.org:a"] - now <= timedelta(hours=1, seconds=5)


async def test_buckets_are_the_tenants(owner_sessionmaker, worker_sessionmaker) -> None:
    a, b = await tenant(owner_sessionmaker), await tenant(owner_sessionmaker)
    scope = Scope("mist.org:shared-name", 1, 0.001)
    assert await _take(worker_sessionmaker, a, [scope]) == 0
    assert await _take(worker_sessionmaker, b, [scope]) == 0  # its own bucket, still full
