# SPDX-License-Identifier: Apache-2.0
"""A sweep's accounting (engine 2b spec §10.3; the owner's M2 review): every active tenant gets one counts-only audit
entry per sweep, zero counts included; the counts are kept with the batches that deleted, so a sweep that dies resumes
and reports each deletion once; one sweep runs at a time, and each batch counts what it deleted, not what it chose."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.core.retention import sweep
from tests.core.retention.support import OLD, TREE_ROWS, count, request, sql, tenant, tree

ZERO = {"runs": 0, "requests": 0, "events": 0, "csv_uploads": 0, "schedules": 0}


async def _entries(owner: Any, tenant_id: uuid.UUID) -> list[tuple[str, dict[str, int]]]:
    async with owner() as s:
        found = await s.execute(text("select target_id, details from audit_log where action = 'retention.sweep' and "
                                     "tenant_id = :t order by seq"), {"t": tenant_id})  # fmt: skip
        return [(r.target_id, r.details) for r in found]


async def test_every_active_tenant_gets_one_counts_only_entry_per_sweep(owner_sessionmaker,
                                                                        retention_sessionmaker) -> None:  # fmt: skip
    busy, idle = await tenant(owner_sessionmaker), await tenant(owner_sessionmaker)
    await tree(owner_sessionmaker, busy, OLD)
    await request(owner_sessionmaker, busy, "refused", OLD)
    done = await sweep.sweep(retention_sessionmaker)
    assert done is not None and done.succeeded and done.tenants == 2
    assert await _entries(owner_sessionmaker, busy["t"]) == [(str(done.id), ZERO | {"runs": 1, "requests": 1})]
    assert await _entries(owner_sessionmaker, idle["t"]) == [(str(done.id), ZERO)]
    again = await sweep.sweep(retention_sessionmaker)
    assert again is not None and again.id != done.id
    assert [e[0] for e in await _entries(owner_sessionmaker, busy["t"])] == [str(done.id), str(again.id)]


class Died(BaseException):
    """The process ending between a tenant's deletions and its audit entry."""


async def test_a_sweep_that_dies_before_its_audit_resumes_and_reports_each_deletion_once(
    monkeypatch, owner_sessionmaker, retention_sessionmaker
) -> None:
    ctx = await tenant(owner_sessionmaker)
    old = await tree(owner_sessionmaker, ctx, OLD)
    real = sweep._audit

    async def dying(*args: Any, **kwargs: Any) -> None:
        raise Died

    monkeypatch.setattr(sweep, "_audit", dying)
    with pytest.raises(Died):
        await sweep.sweep(retention_sessionmaker)
    assert await count(owner_sessionmaker, TREE_ROWS, r=old["root"]) == 0  # deleted, and not yet audited
    assert await _entries(owner_sessionmaker, ctx["t"]) == []
    monkeypatch.setattr(sweep, "_audit", real)
    resumed = await sweep.sweep(retention_sessionmaker)
    assert resumed is not None and resumed.succeeded
    assert await _entries(owner_sessionmaker, ctx["t"]) == [(str(resumed.id), ZERO | {"runs": 1})]
    async with owner_sessionmaker() as s:
        sweeps = (await s.execute(text("select count(*), count(ended_at) from retention_sweeps"))).one()
    assert tuple(sweeps) == (1, 1)  # the same sweep, resumed and ended


async def test_one_sweep_runs_at_a_time(monkeypatch, owner_sessionmaker, retention_sessionmaker, pg_url,
                                        _test_users) -> None:  # fmt: skip
    """Two retention processes: the second finds the first sweeping and makes none of its own."""
    from dewpoint.core.db import make_engine, make_sessionmaker
    from tests.conftest import _url_for

    ctx = await tenant(owner_sessionmaker)
    await tree(owner_sessionmaker, ctx, OLD)
    started, release = asyncio.Event(), asyncio.Event()
    real = sweep.sweep_tenant

    async def slow(*args: Any, **kwargs: Any) -> sweep.Swept:
        started.set()
        await release.wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(sweep, "sweep_tenant", slow)
    first = asyncio.create_task(sweep.sweep(retention_sessionmaker))
    other = make_engine(_url_for(pg_url, "dewpoint_retention"))  # another process's own connections
    try:
        await asyncio.wait_for(started.wait(), 10)
        second = asyncio.create_task(sweep.sweep(make_sessionmaker(other)))
        finished, _ = await asyncio.wait([second], timeout=5)
        assert finished and second.result() is None, "the second sweep didn't step aside"
    finally:
        release.set()
        done = await asyncio.wait_for(first, 10)
        if not second.done():
            await asyncio.wait_for(second, 10)
        await other.dispose()
    assert done is not None and done.succeeded
    assert await _entries(owner_sessionmaker, ctx["t"]) == [(str(done.id), ZERO | {"runs": 1})]


@pytest.mark.parametrize("kind", ["runs", "requests"])
async def test_two_batches_choosing_the_same_rows_count_each_deletion_once(
    monkeypatch, owner_sessionmaker, retention_sessionmaker, kind: str
) -> None:
    """Even without the sweep's lock, two batches that chose the same rows before either deleted count what they
    deleted: the trees and requests go once, and are counted once."""
    ctx = await tenant(owner_sessionmaker)
    for _ in range(3):
        if kind == "runs":
            await tree(owner_sessionmaker, ctx, OLD)
        else:
            await request(owner_sessionmaker, ctx, "refused", OLD)
    chosen, go = asyncio.Event(), asyncio.Event()
    waiting = [0]

    async def both_chose() -> None:
        waiting[0] += 1
        if waiting[0] == 2:
            chosen.set()
        await chosen.wait()
        await go.wait()

    monkeypatch.setattr(sweep, "_after_choosing", both_chose)
    batches = [asyncio.create_task(sweep.sweep_tenant(retention_sessionmaker, ctx["t"])) for _ in range(2)]
    await asyncio.wait_for(chosen.wait(), 10)
    go.set()
    swept = await asyncio.wait_for(asyncio.gather(*batches), 20)
    assert sum(getattr(s, kind) for s in swept) == 3


# A connection's plan for a batch's first delete may scan an index (the rows in their ids' order, as a custom plan on a
# table without statistics does) or the heap (as inserted, as the generic plan does): here each batch's is forced.
BY_INDEX = {"enable_seqscan": "off", "enable_bitmapscan": "off"}
BY_HEAP = {"enable_indexscan": "off", "enable_indexonlyscan": "off", "enable_bitmapscan": "off"}
FIRST = {"runs": ("claim_grants", "root_run_id"), "requests": ("run_requests", "id")}  # what a batch deletes first


async def _lock_waiters(owner: Any, names: tuple[str, ...]) -> int:
    waiting = text("select count(*) from pg_stat_activity where application_name = any(:n) "
                   "and wait_event_type = 'Lock'")  # fmt: skip
    async with owner() as s:
        return int((await s.execute(waiting, {"n": list(names)})).scalar_one())


@pytest.mark.parametrize("kind", ["runs", "requests"])
async def test_two_batches_whose_plans_take_the_same_rows_in_opposite_orders_both_finish(
    monkeypatch, owner_sessionmaker, pg_url, _test_users, kind: str
) -> None:
    """PR #63's CI flake: without the sweep's lock, two batches that chose the same rows deleted them as their plans
    visited them, one in its index's order, one in the heap's, each taking a row the other then waited for (a
    deadlock). Here the orders are opposite and a third transaction holds the middle row until both batches wait: the
    tenant's batches delete in turn, so both finish, and each deletion is counted once."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from dewpoint.core.db import make_sessionmaker, tenant_scope
    from tests.conftest import _url_for

    ctx = await tenant(owner_sessionmaker)
    ids = sorted((uuid.uuid4() for _ in range(3)), reverse=True)  # inserted from the highest: the heap's order reversed
    for i in ids:
        if kind == "runs":
            await tree(owner_sessionmaker, ctx, OLD, root=i)
        else:
            await request(owner_sessionmaker, ctx, "refused", OLD, request_id=i)
    table, column = FIRST[kind]
    engines = {
        name: create_async_engine(
            _url_for(pg_url, "dewpoint_retention"),
            hide_parameters=True,
            connect_args={"server_settings": {"application_name": name, **forced}},
        )
        for name, forced in (("retention-by-index", BY_INDEX), ("retention-by-heap", BY_HEAP))
    }
    makers = [make_sessionmaker(e) for e in engines.values()]
    chosen, go = asyncio.Event(), asyncio.Event()
    waiting = [0]

    async def both_chose() -> None:
        waiting[0] += 1
        if waiting[0] == 2:
            chosen.set()
        await chosen.wait()
        await go.wait()

    monkeypatch.setattr(sweep, "_after_choosing", both_chose)
    batches: list[asyncio.Task[sweep.Swept]] = []
    try:
        scans = []
        for maker in makers:  # the premise: one plan scans the index, the other the heap
            async with maker() as s, s.begin():
                await tenant_scope(s, ctx["t"])
                plan = (await s.execute(text(f"explain (format json) delete from {table} where {column} = any(:r)"),  # noqa: S608
                                        {"r": ids})).scalar_one()  # fmt: skip
                scans.append(plan[0]["Plan"]["Plans"][0]["Node Type"])
        assert scans == ["Index Scan", "Seq Scan"]
        async with owner_sessionmaker() as gate, gate.begin():
            await gate.execute(text(f"select 1 from {table} where {column} = :m for update"), {"m": ids[1]})  # noqa: S608
            batches += [asyncio.create_task(sweep.sweep_tenant(m, ctx["t"])) for m in makers]
            await asyncio.wait_for(chosen.wait(), 10)
            go.set()
            for _ in range(500):  # until both batches wait: for the middle row, or one for the other
                if await _lock_waiters(owner_sessionmaker, tuple(engines)) == 2:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("the batches didn't both wait")
        swept = await asyncio.wait_for(asyncio.gather(*batches, return_exceptions=True), 20)  # both settled
    finally:
        go.set()
        for b in batches:
            b.cancel()
        await asyncio.gather(*batches, return_exceptions=True)
        for e in engines.values():
            await e.dispose()
    assert [type(s).__name__ for s in swept] == ["Swept", "Swept"], swept
    assert sum(getattr(s, kind) for s in swept) == 3


async def test_sweep_records_older_than_30_days_go(owner_sessionmaker, retention_sessionmaker) -> None:
    await sql(owner_sessionmaker, "insert into retention_sweeps (started_at, ended_at, succeeded, tenants, lag_s) "
              "values (now() - interval '31 days', now() - interval '31 days', true, 0, 0), "
              "(now() - interval '29 days', now() - interval '29 days', true, 0, 0)")  # fmt: skip
    done = await sweep.sweep(retention_sessionmaker)
    async with owner_sessionmaker() as s:
        ages = list((await s.execute(text("select extract(day from now() - started_at)::int from retention_sweeps "
                                          "order by started_at"))).scalars())  # fmt: skip
    assert done is not None and ages == [29, 0]


async def test_a_tenant_that_failed_keeps_the_sweep_unsuccessful_across_a_crash(
    monkeypatch, owner_sessionmaker, retention_sessionmaker
) -> None:
    """The owner's second M2 review: a tenant's failure is kept with its counts, so a sweep that dies after auditing
    it and before ending, once resumed, still ends unsuccessful, and never meets the SLO."""
    from dewpoint.core.retention import slo

    broken, fine = await tenant(owner_sessionmaker), await tenant(owner_sessionmaker)
    real_tenant, real_close = sweep.sweep_tenant, sweep._close

    async def failing(sessionmaker: Any, tenant_id: uuid.UUID, **kwargs: Any) -> sweep.Swept:
        if tenant_id == broken["t"]:
            raise ConnectionError("lost")
        return await real_tenant(sessionmaker, tenant_id, **kwargs)

    async def dying(*args: Any, **kwargs: Any) -> None:
        raise Died

    monkeypatch.setattr(sweep, "sweep_tenant", failing)
    monkeypatch.setattr(sweep, "_close", dying)
    with pytest.raises(Died):
        await sweep.sweep(retention_sessionmaker)
    monkeypatch.setattr(sweep, "sweep_tenant", real_tenant)
    monkeypatch.setattr(sweep, "_close", real_close)
    resumed = await sweep.sweep(retention_sessionmaker)
    assert resumed is not None and not resumed.succeeded
    assert [e[0] for e in await _entries(owner_sessionmaker, broken["t"])] == [str(resumed.id)]
    assert [e[0] for e in await _entries(owner_sessionmaker, fine["t"])] == [str(resumed.id)]
    async with owner_sessionmaker() as s:
        assert await slo.healthy(s) is False


async def test_a_tenant_erased_after_a_crash_has_its_counts_audited_and_nothing_more_deleted(
    monkeypatch, owner_sessionmaker, retention_sessionmaker
) -> None:
    """The owner's second M2 review: counts kept by batches that committed are audited even once the tenant is no
    longer active; recovery deletes nothing more of it (erasure's to sweep)."""
    ctx = await tenant(owner_sessionmaker)
    await tree(owner_sessionmaker, ctx, OLD)
    await tree(owner_sessionmaker, ctx, OLD)
    real = sweep._audit

    async def dying(*args: Any, **kwargs: Any) -> None:
        raise Died

    monkeypatch.setattr(sweep, "_audit", dying)
    with pytest.raises(Died):
        await sweep.sweep(retention_sessionmaker, batch=1)
    monkeypatch.setattr(sweep, "_audit", real)
    await sql(owner_sessionmaker, "update tenants set status = 'erasing' where id = :t", t=ctx["t"])
    later = await tree(owner_sessionmaker, ctx, OLD)  # past the cutoff, but its tenant is being erased
    resumed = await sweep.sweep(retention_sessionmaker)
    assert resumed is not None and resumed.succeeded
    assert await _entries(owner_sessionmaker, ctx["t"]) == [(str(resumed.id), ZERO | {"runs": 2})]
    assert await count(owner_sessionmaker, TREE_ROWS, r=later["root"]) > 0
    async with owner_sessionmaker() as s:
        open_rows = (
            await s.execute(text("select count(*) from retention_sweep_tenants where audited_at is null"))
        ).scalar()
    assert open_rows == 0
