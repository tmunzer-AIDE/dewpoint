# SPDX-License-Identifier: Apache-2.0
"""What the workflows list shows of each (sub-project 4, B3): its last live root run and, apart, its last simulated one;
its root runs in the last 24 hours, live and simulated apart; whether its draft differs from its active version; why it
needs attention, from live runs only. Its reads don't grow with its workflows."""

import uuid
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
    """A run names its own workflow's version (`runs_version_fk`), so no row of another tenant's can claim this
    tenant's workflow. What's left to prove is the statements' own tenant filter, with row-level security out of the
    way (the owner's session): asked, for this tenant, about another tenant's workflow, they find no run of it."""
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
