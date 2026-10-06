# SPDX-License-Identifier: Apache-2.0
"""What the workflows list shows of each (sub-project 4, B3): its last live root run and, apart, its last simulated one;
its root runs in the last 24 hours, live and simulated apart; whether its draft differs from its active version; why it
needs attention, from live runs only. Its reads don't grow with its workflows."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from dewpoint.engine.graph.model import graph_hash, parse_graph
from tests.apps.api.helpers import session_client
from tests.support.graphs import G
from tests.support.registry import sync_test_plugins

GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data()
WORKFLOW_TABLES = ("workflows", "workflow_versions", "runs", "node_type_versions", "cel_profiles")


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


async def add_run(owner, tid, wid, vid, *, status, mode="live", hours_ago=1.0, parent=None) -> uuid.UUID:
    """A run row as the dispatcher writes one: a root run, or a sub-flow's when `parent` is given."""
    rid = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text(
                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at,"
                " iterations, kind, parent_run_id, parent_step_id) values (:i, :t, :w, :v, :m, :st,"
                " now() - make_interval(secs => :ago), 0, :k, :p, :ps)"
            ),
            {
                "i": rid, "t": tid, "w": wid, "v": vid, "m": mode, "st": status, "ago": hours_ago * 3600,
                "k": "subflow" if parent else "run", "p": parent, "ps": uuid.uuid4() if parent else None,
            },
        )  # fmt: skip
    return rid


async def published(c, tid) -> tuple[str, str]:
    wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": f"W {uuid.uuid4().hex[:6]}", "draft": GRAPH})).json()
    v = (await c.post(f"/api/v1/t/{tid}/workflows/{wf['id']}/publish", headers={"If-Match": "1"})).json()
    return wf["id"], v["version_id"]


async def test_the_list_says_how_each_workflows_runs_went(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wid, vid = await published(c, tid)
        root = await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", hours_ago=30)  # out of the 24 h
        await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", hours_ago=2)
        await add_run(owner_sessionmaker, tid, wid, vid, status="failed", hours_ago=0.5)  # the last live root run
        await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", mode="simulate", hours_ago=0.2)
        await add_run(owner_sessionmaker, tid, wid, vid, status="running", hours_ago=0.1, parent=root)  # a sub-run
        quiet, _ = await published(c, tid)
        rows = {w["id"]: w for w in (await c.get(f"/api/v1/t/{tid}/workflows")).json()}
    busy = rows[wid]
    assert busy["draft_graph_hash"] == graph_hash(parse_graph(GRAPH))
    assert busy["last_run"]["status"] == "failed" and busy["last_simulation"]["status"] == "succeeded"
    assert busy["runs_24h"] == {"live": 2, "simulate": 1}
    assert busy["needs_attention"] == ["last_run_failed"]  # the later successful simulation doesn't clear it
    assert busy["unpublished_changes"] is False
    assert rows[quiet]["last_run"] is None and rows[quiet]["last_simulation"] is None
    assert rows[quiet]["runs_24h"] == {"live": 0, "simulate": 0} and rows[quiet]["needs_attention"] == []


async def test_a_failed_simulation_never_needs_attention(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wid, vid = await published(c, tid)
        await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", hours_ago=2)
        await add_run(owner_sessionmaker, tid, wid, vid, status="failed", mode="simulate", hours_ago=1)
        row = (await c.get(f"/api/v1/t/{tid}/workflows/{wid}")).json()
    assert row["last_run"]["status"] == "succeeded" and row["last_simulation"]["status"] == "failed"
    assert row["needs_attention"] == []


async def test_another_tenants_runs_never_count(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    _, otid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wid, vid = await published(c, tid)
        # A row in the other tenant claiming this tenant's workflow, with that workflow's own version: `runs_version_fk`
        # holds (the version is the workflow's) and has no tenant column, so only row-level security and the
        # statements' tenant filter keep it out.
        await add_run(owner_sessionmaker, otid, wid, vid, status="failed")
        row = (await c.get(f"/api/v1/t/{tid}/workflows/{wid}")).json()
        listed = (await c.get(f"/api/v1/t/{tid}/workflows")).json()
    assert row["last_run"] is None and row["runs_24h"] == {"live": 0, "simulate": 0}
    assert row["needs_attention"] == [] and [w["last_run"] for w in listed] == [None]
    async with owner_sessionmaker() as s:  # the row is there, under the other tenant
        found = await s.execute(text("select tenant_id from runs where workflow_id = :w"), {"w": wid})
        assert [r.tenant_id for r in found] == [otid]


async def test_the_statements_filter_by_tenant_themselves(app, owner_sessionmaker, api_settings) -> None:
    """Row-level security keeps another tenant's runs from the API's role; the statements also filter by tenant
    themselves. With row-level security out of the way (the owner's session), asked for this tenant about another
    tenant's workflow, they find no run of it, while the row is there for its own tenant."""
    from dewpoint.apps import workflow_summary

    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    other, otid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c, other:
        owid, ovid = await published(other, otid)
        await add_run(owner_sessionmaker, otid, owid, ovid, status="failed")
        assert (await c.get(f"/api/v1/t/{tid}/workflows")).json() == []
    theirs = uuid.UUID(owid)
    async with owner_sessionmaker() as s:
        mine = (await workflow_summary.run_stats(s, tid, [theirs]))[theirs]
        found = (await workflow_summary.run_stats(s, otid, [theirs]))[theirs]
    assert (mine.last_live, mine.live_24h) == (None, 0)
    # The row is there: the tenant filter alone kept it out.
    assert found.last_live is not None and found.last_live.status == "failed"


async def test_a_moved_step_is_an_unpublished_change(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        new = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Never", "draft": GRAPH})).json()
        assert new["unpublished_changes"] is True and new["active_version_number"] is None  # ruling 6
        wid, _ = await published(c, tid)
        base = f"/api/v1/t/{tid}/workflows/{wid}"
        same = (await c.put(f"{base}/draft", json=GRAPH, headers={"If-Match": "1"})).json()
        assert (same["draft_revision"], same["unpublished_changes"]) == (2, False)
        assert (same["graph_hash"], same["active_version_number"]) == (graph_hash(parse_graph(GRAPH)), 1)
        moved = G().node("a", "testkit.echo@1", {"value": 1}).data()
        moved["nodes"][0]["position"] = {"x": 40, "y": 0}
        saved = (await c.put(f"{base}/draft", json=moved, headers={"If-Match": "2"})).json()
        assert (saved["draft_revision"], saved["unpublished_changes"]) == (3, True)
        row = (await c.get(base)).json()
        assert row["unpublished_changes"] is True and row["draft_graph_hash"] == graph_hash(parse_graph(moved))


async def test_a_save_compares_with_the_version_active_when_it_lands(
    app, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """An activation commits between the route's read of the workflow and its compare-and-swap: the answer names the
    version active when the save landed, and compares with that one (the owner's review of revision 2)."""
    from dewpoint.core.workflows import service

    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wid, v1 = await published(c, tid)  # version 1 is GRAPH
        base = f"/api/v1/t/{tid}/workflows/{wid}"
        moved = G().node("a", "testkit.echo@1", {"value": 1}).data()
        moved["nodes"][0]["position"] = {"x": 40, "y": 0}
        await c.put(f"{base}/draft", json=moved, headers={"If-Match": "1"})
        v2 = (await c.post(f"{base}/publish", headers={"If-Match": "2"})).json()  # version 2 is `moved`, active
        real = service.save_draft

        async def activated_meanwhile(s, wf, **kw):  # wf was read with version 2 active
            async with owner_sessionmaker() as other, other.begin():  # as an activation of version 1 commits
                await other.execute(
                    text("update workflows set active_version_id = :v where id = :w"),
                    {"v": uuid.UUID(v1), "w": uuid.UUID(wid)},
                )
            return await real(s, wf, **kw)

        monkeypatch.setattr(service, "save_draft", activated_meanwhile)
        saved = (await c.put(f"{base}/draft", json=moved, headers={"If-Match": "2"})).json()
    assert v2["number"] == 2
    assert (saved["active_version_id"], saved["active_version_number"]) == (v1, 1)
    assert saved["unpublished_changes"] is True  # `moved` against version 1, never against the stale version 2


async def test_a_version_that_cant_run_needs_attention(
    app, owner_sessionmaker, api_settings, admin_sessionmaker
) -> None:
    from dewpoint.core.plugins import lifecycle
    from dewpoint.core.plugins.lifecycle import Entry

    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wid, _ = await published(c, tid)
        base = f"/api/v1/t/{tid}/workflows/{wid}"
        assert (await c.patch(base, json={"enabled": False})).json()["enabled"] is False
        async with admin_sessionmaker() as s, s.begin():  # as test_workflows.py retires: its only user is disabled
            assert (await lifecycle.retire(s, Entry("node", "testkit.echo@1"))).applied
        row = (await c.get(base)).json()
    assert row["executable"] is False and row["needs_attention"] == ["not_executable"]


async def statements_listing(c, tid) -> int:
    """The statements one list request runs against a workflow's tables (the session's own reads are left out: a
    session's bookkeeping may differ from one request to the next)."""
    seen: list[str] = []

    def on(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", on)
    try:
        assert (await c.get(f"/api/v1/t/{tid}/workflows")).status_code == 200
    finally:
        event.remove(Engine, "before_cursor_execute", on)
    return len([s for s in seen if any(t in s for t in WORKFLOW_TABLES)])


async def test_the_lists_reads_dont_grow_with_its_workflows(app, owner_sessionmaker, api_settings) -> None:
    """Counted in statements, never time (the owner's review of 325fc14): two workflows or twelve, published or not,
    with runs or without, the list reads as often."""
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        for _ in range(2):
            wid, vid = await published(c, tid)
            await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded")
        few = await statements_listing(c, tid)
        for n in range(10):
            if n % 2:
                await c.post(f"/api/v1/t/{tid}/workflows", json={"name": f"Draft {n}", "draft": GRAPH})
            else:
                wid, vid = await published(c, tid)
                await add_run(owner_sessionmaker, tid, wid, vid, status="failed", mode="simulate")
        many = await statements_listing(c, tid)
    assert few == many <= 6  # workflows, active versions, two lifecycle reads at most, last runs, counts


# The last-runs read (4b ruling 5, the owner's review of M1): one batched LATERAL statement over `runs_workflow_last`
# (migration 0047). REFERENCE is the statement it replaced, kept to prove the two answer the same.
REFERENCE = text(
    "select distinct on (workflow_id, mode) workflow_id, mode, status, coalesce(ended_at, started_at, queued_at) as at"
    " from runs where tenant_id = :tenant and kind = 'run' and workflow_id = any(cast(:ids as uuid[]))"
    " order by workflow_id, mode, queued_at desc, id desc"
)


async def put_run(owner, tid, wid, vid, *, mode, status, at, rid=None, parent=None) -> uuid.UUID:
    """A run queued at `at` exactly, with the id given (equal timestamps are ordered by id)."""
    rid = rid or uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text(
                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at,"
                " iterations, kind, parent_run_id, parent_step_id) values (:i, :t, :w, :v, :m, :st, :at, 0, :k, :p,"
                " :ps)"
            ),
            {
                "i": rid, "t": tid, "w": wid, "v": vid, "m": mode, "st": status, "at": at,
                "k": "subflow" if parent else "run", "p": parent, "ps": uuid.uuid4() if parent else None,
            },
        )  # fmt: skip
    return rid


async def test_the_index_is_the_one_reserved(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        found = await s.execute(text("select indexdef from pg_indexes where indexname = 'runs_workflow_last'"))
        definition = found.scalar_one()
    assert definition == (
        "CREATE INDEX runs_workflow_last ON public.runs USING btree (workflow_id, mode, queued_at DESC, id DESC)"
        " WHERE ((kind)::text = 'run'::text)"
    )


async def test_the_last_runs_read_answers_as_the_statement_it_replaced(
    app, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    """Both modes of one workflow, a quiet workflow, equal timestamps (the greater id wins), a sub-run newer than its
    root, and another tenant's run of the same workflow: the LATERAL read and the DISTINCT ON reference agree whole."""
    from dewpoint.apps import workflow_summary
    from dewpoint.core.db import tenant_scope

    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    _, otid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        (a, av), (b, bv), (quiet, _) = [await published(c, tid) for _ in range(3)]
    t0 = datetime.now(UTC) - timedelta(hours=1)
    low, high = sorted((uuid.uuid4(), uuid.uuid4()))
    await put_run(owner_sessionmaker, tid, a, av, mode="live", status="failed", at=t0, rid=low)
    await put_run(owner_sessionmaker, tid, a, av, mode="live", status="succeeded", at=t0, rid=high)
    await put_run(owner_sessionmaker, tid, a, av, mode="live", status="failed", at=t0 - timedelta(minutes=5))
    await put_run(owner_sessionmaker, tid, a, av, mode="simulate", status="cancelled", at=t0 - timedelta(minutes=1))
    root = await put_run(owner_sessionmaker, tid, b, bv, mode="live", status="succeeded", at=t0 - timedelta(minutes=9))
    await put_run(owner_sessionmaker, tid, b, bv, mode="live", status="failed", at=t0, parent=root)
    await put_run(owner_sessionmaker, otid, b, bv, mode="simulate", status="failed", at=t0)
    ids = [uuid.UUID(w) for w in (a, b, quiet)]
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, tid)
        stats = await workflow_summary.run_stats(s, tid, ids)
        found = await s.execute(REFERENCE, {"tenant": tid, "ids": ids})
        reference = {(r.workflow_id, r.mode): (r.status, r.at) for r in found}
    got = {
        (wid, mode): (last.status, last.at)
        for wid, st in stats.items()
        for mode, last in (("live", st.last_live), ("simulate", st.last_simulated))
        if last is not None
    }
    assert got == reference
    assert got == {
        (ids[0], "live"): ("succeeded", t0),  # the greater id of the two at t0
        (ids[0], "simulate"): ("cancelled", t0 - timedelta(minutes=1)),
        (ids[1], "live"): ("succeeded", t0 - timedelta(minutes=9)),  # the root, never its sub-run
    }
    assert stats[ids[2]] == workflow_summary.RunStats(None, None, 0, 0)


def runs_scanned(node: dict[str, Any]) -> tuple[int, int, set[str]]:
    """What a plan's scans of `runs` cost over every loop: the rows they read (kept or filtered out), the pages they
    touched, and how (each scan's node type and index; a sort anywhere counts as one)."""
    rows, pages, how = 0, 0, {node["Node Type"]} if node["Node Type"] in ("Sort", "Incremental Sort") else set()
    if node.get("Relation Name") == "runs":
        rows = round((node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node["Actual Loops"])
        pages = node.get("Shared Hit Blocks", 0) + node.get("Shared Read Blocks", 0)
        how = {f"{node['Node Type']} {node.get('Index Name', '')}".strip()}
    for child in node.get("Plans", []):
        r, p, h = runs_scanned(child)
        rows, pages, how = rows + r, pages + p, how | h
    return rows, pages, how


async def test_the_last_runs_read_examines_one_run_per_workflow_and_mode(
    app, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    """Counted in rows and pages, never time (4b ruling 5; ledger M5): however long a workflow's history, the read
    looks up each workflow and mode once in `runs_workflow_last`, in order, stopping at the first row. The history here
    is the one that turned the planner to `runs_tenant_queued` when the mode was an equality: one workflow's live runs
    only, analyzed, and a quiet workflow. It then read every run of the tenant's for each of the three workflows and
    modes with none."""
    from dewpoint.apps import workflow_summary
    from dewpoint.core.db import tenant_scope

    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        (a, av), (b, _) = [await published(c, tid) for _ in range(2)]
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(
            text(
                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at,"
                " iterations, kind) select gen_random_uuid(), :t, :w, :v, 'live', 'succeeded',"
                " now() - make_interval(secs => g), 0, 'run' from generate_series(1, 3000) g"
            ),
            {"t": tid, "w": a, "v": av},
        )
        await s.execute(text("analyze runs"))
    params = {"tenant": tid, "ids": [uuid.UUID(a), uuid.UUID(b)]}  # b is quiet; a never simulated
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, tid)
        query = text(f"explain (analyze, buffers, format json) {workflow_summary.LAST_RUNS.text}")
        plan = (await s.execute(query, params)).scalar_one()[0]["Plan"]
    rows, pages, how = runs_scanned(plan)
    assert how == {"Index Scan runs_workflow_last"}  # ordered, stopping at the first row: no bitmap, no sort
    assert rows <= 4 and pages <= 16  # 2 workflows x 2 modes: one lookup each, a few pages of the index and heap
