# SPDX-License-Identifier: Apache-2.0
"""The retention sweep (engine 2b spec §10.1, §10.3), as its own role, `dewpoint_retention`, per tenant under its scope,
in batches: a terminal root's whole tree past the cutoff (runs, steps, claims, grants, its secret index, its request
and envelope, together); terminal requests that never started, with their inputs; terminal events, freeing their
retained counters; expired uploads; tombstones Temporal reported gone. Nothing of a tree still running, no request
queued or starting, no pending event. A crash resumes: every batch commits on its own."""

import uuid

import pytest
from sqlalchemy import text

from dewpoint.core.retention import sweep
from tests.core.ingress.support import endpoint, record
from tests.core.retention.support import OLD, RECENT, TREE_ROWS, count, request, run, sql, tenant, tree

RETAINED = ("runs", "run_steps", "step_outputs", "run_inputs", "run_secret_index", "claim_grants", "run_requests",
            "inbound_events", "csv_uploads", "schedules")  # fmt: skip


async def test_a_tree_past_its_cutoff_goes_whole_with_its_request(owner_sessionmaker, retention_sessionmaker) -> None:
    ctx = await tenant(owner_sessionmaker)
    old, recent = await tree(owner_sessionmaker, ctx, OLD), await tree(owner_sessionmaker, ctx, RECENT)
    before = await count(owner_sessionmaker, TREE_ROWS, r=old["root"])
    swept = await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])
    assert swept.runs == 1 and before == 2 + 2 + 1 + 2 + 1 + 1 + 1  # runs, steps, output, envelope+claim, grant, ...
    assert await count(owner_sessionmaker, TREE_ROWS, r=old["root"]) == 0
    assert await count(owner_sessionmaker, TREE_ROWS, r=recent["root"]) == before


@pytest.mark.parametrize("shape", ["root_running", "sub_running", "request_queued", "request_starting"])
async def test_nothing_of_a_tree_still_running_or_a_request_still_pending_is_deleted(
    owner_sessionmaker, retention_sessionmaker, shape: str
) -> None:
    ctx = await tenant(owner_sessionmaker)
    built = {
        "root_running": lambda: tree(owner_sessionmaker, ctx, None, sub_ago=OLD),
        "sub_running": lambda: tree(owner_sessionmaker, ctx, OLD, sub_ago=None),
        "request_queued": lambda: tree(owner_sessionmaker, ctx, OLD, request_status="queued"),
        "request_starting": lambda: tree(owner_sessionmaker, ctx, OLD, request_status="starting"),
    }[shape]
    kept = await built()
    before = await count(owner_sessionmaker, TREE_ROWS, r=kept["root"])
    assert (await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])).runs == 0
    assert await count(owner_sessionmaker, TREE_ROWS, r=kept["root"]) == before


async def test_a_run_from_before_requests_goes_with_its_tree(owner_sessionmaker, retention_sessionmaker) -> None:
    ctx = await tenant(owner_sessionmaker)
    old = await tree(owner_sessionmaker, ctx, OLD, request_status=None)
    assert (await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])).runs == 1
    assert await count(owner_sessionmaker, TREE_ROWS, r=old["root"]) == 0


async def test_terminal_requests_that_never_started_go_with_their_inputs(owner_sessionmaker,
                                                                         retention_sessionmaker) -> None:  # fmt: skip
    ctx = await tenant(owner_sessionmaker)
    gone = [await request(owner_sessionmaker, ctx, status, OLD) for status in ("refused", "cancelled", "dead")]
    kept = [await request(owner_sessionmaker, ctx, "cancelled", RECENT),
            await request(owner_sessionmaker, ctx, "queued", None)]  # fmt: skip
    assert (await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])).requests == 3
    for rid, there in [(r, False) for r in gone] + [(r, True) for r in kept]:
        rows = await count(owner_sessionmaker, "select (select count(*) from run_requests where id = :r) + "
                           "(select count(*) from run_inputs where root_run_id = :r)", r=rid)  # fmt: skip
        assert (rows > 0) == there, rid


@pytest.mark.usefixtures("development_deployment")
async def test_terminal_events_past_the_cutoff_go_and_free_their_retained_counters(
    owner_sessionmaker, ingress_sessionmaker, retention_sessionmaker
) -> None:
    t, endpoint_id = await endpoint(owner_sessionmaker)
    ctx = await tenant(owner_sessionmaker, tenant_id=t)
    sizes = {"matched": 70, "unmatched": 71, "cancelled": 72, "dead": 73, "recent": 74, "pending": 75}
    ids = {name: uuid.uuid4() for name in sizes}
    await record(ingress_sessionmaker, endpoint_id, [(None, None, b"x" * n) for n in sizes.values()],
                 ids=list(ids.values()))  # fmt: skip
    for name, ago in (("matched", OLD), ("unmatched", OLD), ("cancelled", OLD), ("dead", OLD), ("recent", RECENT)):
        await sql(owner_sessionmaker, "update inbound_events set status = :s, reason = 'r', ended_at = now() - "
                  "cast(:ago as interval) where id = :i", s="matched" if name == "recent" else name, ago=ago,
                  i=ids[name])  # fmt: skip
    counters = (
        "select e.retained_events, e.retained_bytes, c.retained_events, c.retained_bytes from webhook_endpoints e "
        "join tenant_event_counters c on c.tenant_id = e.tenant_id where e.id = :e"
    )
    async with owner_sessionmaker() as s:
        before = tuple((await s.execute(text(counters), {"e": endpoint_id})).one())
    assert (await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])).events == 4
    async with owner_sessionmaker() as s:
        left = set((await s.execute(text("select id from inbound_events where endpoint_id = :e"),
                                    {"e": endpoint_id})).scalars())  # fmt: skip
        after = tuple((await s.execute(text(counters), {"e": endpoint_id})).one())
    assert left == {ids["recent"], ids["pending"]}
    freed = sizes["matched"] + sizes["unmatched"] + sizes["cancelled"] + sizes["dead"]
    assert after == (before[0] - 4, before[1] - freed, before[2] - 4, before[3] - freed)


async def test_expired_uploads_go(owner_sessionmaker, retention_sessionmaker) -> None:
    ctx = await tenant(owner_sessionmaker)
    upload = ("insert into csv_uploads (id, tenant_id, owner_id, workflow_id, staged, file_digest, digest_key_version, "
              "size_bytes, row_count, created_at, expires_at) values (:i, :t, :u, :w, 'x', :d, 1, 1, 1, "
              "now() - cast(:age as interval), now() - cast(:age as interval) + interval '1 hour')")  # fmt: skip
    expired, live = uuid.uuid4(), uuid.uuid4()
    await sql(owner_sessionmaker, upload, i=expired, t=ctx["t"], u=ctx["u"], w=ctx["w"], d=b"\x00" * 32, age=OLD)
    await sql(owner_sessionmaker, upload, i=live, t=ctx["t"], u=ctx["u"], w=ctx["w"], d=b"\x00" * 32,
              age=RECENT / 2)  # fmt: skip
    assert (await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])).csv_uploads == 1
    left = await count(owner_sessionmaker, "select count(*) from csv_uploads where id = any(:i)", i=[expired, live])
    assert left == 1


async def test_a_tombstone_goes_once_temporal_reported_its_schedule_gone(owner_sessionmaker,
                                                                         retention_sessionmaker) -> None:  # fmt: skip
    ctx = await tenant(owner_sessionmaker)
    schedule = ("insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by, generation, "
                "synced_generation, deleted_at) values (:i, :t, :w, 60, 'live', :input, :u, 2, :synced, "
                "case when :deleted then now() end)")  # fmt: skip
    settled, unsettled, live = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for sid, synced, given in ((settled, 2, None), (unsettled, 1, None), (live, 2, b"\x01")):
        await sql(owner_sessionmaker, schedule, i=sid, t=ctx["t"], w=ctx["w"], u=ctx["u"], synced=synced, input=given,
                  deleted=given is None)  # fmt: skip
    assert (await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])).schedules == 1
    async with owner_sessionmaker() as s:
        left = set((await s.execute(text("select id from schedules where tenant_id = :t"), {"t": ctx["t"]})).scalars())
    assert left == {unsettled, live}


async def test_batches_resume_until_nothing_is_left(owner_sessionmaker, retention_sessionmaker) -> None:
    """Each batch commits on its own, so a sweep that stops resumes; one with nothing to delete deletes nothing."""
    ctx = await tenant(owner_sessionmaker)
    roots = [(await tree(owner_sessionmaker, ctx, OLD))["root"] for _ in range(3)]
    requests = [await request(owner_sessionmaker, ctx, "refused", OLD) for _ in range(3)]
    swept = await sweep.sweep_tenant(retention_sessionmaker, ctx["t"], batch=2)
    assert (swept.runs, swept.requests) == (3, 3)
    assert sum([await count(owner_sessionmaker, TREE_ROWS, r=r) for r in roots + requests]) == 0
    again = await sweep.sweep_tenant(retention_sessionmaker, ctx["t"], batch=2)
    assert (again.runs, again.requests, again.events, again.csv_uploads, again.schedules) == (0, 0, 0, 0, 0)


async def test_a_tenant_with_a_longer_retention_keeps_what_another_loses(owner_sessionmaker,
                                                                         retention_sessionmaker) -> None:  # fmt: skip
    short, default = await tenant(owner_sessionmaker), await tenant(owner_sessionmaker, days=None)
    lost, kept = await tree(owner_sessionmaker, short, OLD), await tree(owner_sessionmaker, default, OLD)
    await sweep.sweep(retention_sessionmaker)
    assert await count(owner_sessionmaker, TREE_ROWS, r=lost["root"]) == 0
    assert await count(owner_sessionmaker, TREE_ROWS, r=kept["root"]) > 0


async def test_a_sweep_is_recorded_with_its_lag_and_audited_per_tenant_with_counts_only(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    """Lag: how far past its cutoff the oldest data still stored is. A tree held back by a run still going past its
    root's cutoff counts; a sweep that leaves nothing past a cutoff has none."""
    ctx = await tenant(owner_sessionmaker)
    await tree(owner_sessionmaker, ctx, OLD)
    await request(owner_sessionmaker, ctx, "refused", OLD)
    done = await sweep.sweep(retention_sessionmaker)
    async with owner_sessionmaker() as s:
        row = (await s.execute(text("select started_at < ended_at, succeeded, lag_s from retention_sweeps "
                                    "where id = :i"), {"i": done.id})).one()  # fmt: skip
        entries = (await s.execute(text("select tenant_id, actor_id, details from audit_log where action = "
                                        "'retention.sweep' and tenant_id = :t"), {"t": ctx["t"]})).all()  # fmt: skip
    assert tuple(row) == (True, True, 0)
    assert [(e.tenant_id, e.actor_id, e.details) for e in entries] == [
        (ctx["t"], None, {"runs": 1, "requests": 1, "events": 0, "csv_uploads": 0, "schedules": 0}),
    ]  # fmt: skip
    held = await tree(owner_sessionmaker, ctx, OLD, sub_ago=None)  # its root ended 2 days ago: 1 day past the cutoff
    later = await sweep.sweep(retention_sessionmaker)
    assert await count(owner_sessionmaker, TREE_ROWS, r=held["root"]) > 0
    assert 86_000 < later.lag_s < 87_000


async def test_only_the_retention_role_deletes_retained_rows(owner_sessionmaker) -> None:
    """§10.3: `DELETE` on the retained tables is the retention role's alone (steps go with their run)."""
    async with owner_sessionmaker() as s:
        found = await s.execute(text("select table_name, grantee from information_schema.role_table_grants where "
                                     "privilege_type = 'DELETE' and table_name = any(:t) and grantee like 'dewpoint%'"),
                                {"t": list(RETAINED)})  # fmt: skip
        deleters = {(r.table_name, r.grantee) for r in found}
    assert deleters == {(t, "dewpoint_retention") for t in RETAINED if t != "run_steps"}


async def test_the_retention_role_reads_only_the_tenant_it_sweeps(owner_sessionmaker, retention_sessionmaker) -> None:
    from dewpoint.core.db import tenant_scope

    first, second = await tenant(owner_sessionmaker), await tenant(owner_sessionmaker)
    await run(owner_sessionmaker, first, OLD)
    await run(owner_sessionmaker, second, OLD)
    async with retention_sessionmaker() as s, s.begin():
        await tenant_scope(s, first["t"])
        seen = set((await s.execute(text("select tenant_id from runs"))).scalars())
    assert seen == {first["t"]}


@pytest.mark.usefixtures("development_deployment")
async def test_every_endpoints_events_go_in_one_sweep(owner_sessionmaker, ingress_sessionmaker,
                                                      retention_sessionmaker) -> None:  # fmt: skip
    """Events are deleted an endpoint at a time, under its row's lock: a short batch on one doesn't end the others'."""
    t, first = await endpoint(owner_sessionmaker)
    ctx, second = await tenant(owner_sessionmaker, tenant_id=t), uuid.uuid4()
    await sql(owner_sessionmaker, "insert into webhook_endpoints (id, tenant_id, name, created_by, auth_kind, "
              "bearer_digest, dedupe_key) select :e, tenant_id, 'second', created_by, auth_kind, bearer_digest, "
              "dedupe_key from webhook_endpoints where id = :f", e=second, f=first)  # fmt: skip
    for endpoint_id in (first, second):
        await record(ingress_sessionmaker, endpoint_id, [(None, None, b"x" * 10)])
    await sql(owner_sessionmaker, "update inbound_events set status = 'matched', reason = 'r', ended_at = now() - "
              "cast(:ago as interval) where tenant_id = :t", ago=OLD, t=t)  # fmt: skip
    assert (await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])).events == 2
    assert await count(owner_sessionmaker, "select count(*) from inbound_events where tenant_id = :t", t=t) == 0


async def test_a_tenant_being_erased_is_left_to_its_erasure(owner_sessionmaker, retention_sessionmaker) -> None:
    """Retention sweeps only active tenants, under the lifecycle lock an erasure takes exclusively (§6.5)."""
    ctx = await tenant(owner_sessionmaker)
    old = await tree(owner_sessionmaker, ctx, OLD)
    await sql(owner_sessionmaker, "update tenants set status = 'erasing' where id = :t", t=ctx["t"])
    assert (await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])).runs == 0
    assert await count(owner_sessionmaker, TREE_ROWS, r=old["root"]) > 0
