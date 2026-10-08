# SPDX-License-Identifier: Apache-2.0
"""A published version read whole (sub-project 4, B4a): its graph, how its expressions run, and its engine ABI. And
publish bound to the version number the editor named (4b ruling 17)."""

import asyncio
import uuid

import pytest

from dewpoint.engine import ENGINE_ABI
from tests.apps.api.helpers import member_client, session_client
from tests.support.graphs import G, cel
from tests.support.registry import sync_test_plugins

GRAPH = G().node("a", "testkit.echo@1", {"value": cel("1 + 1")}).data()


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


async def test_a_version_is_read_whole(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "W", "draft": GRAPH})).json()
        base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
        v = (await c.post(f"{base}/publish", headers={"If-Match": "1"})).json()
        listed = (await c.get(f"{base}/versions")).json()
        got = await c.get(f"{base}/versions/{v['version_id']}")
    assert listed[0]["engine_abi"] == ENGINE_ABI
    assert got.status_code == 200, got.text
    body = got.json()
    assert (body["number"], body["engine_abi"], body["active"]) == (1, ENGINE_ABI, True)
    assert [n["key"] for n in body["graph"]["nodes"]] == ["a"]
    expression = {"node": GRAPH["nodes"][0]["id"], "field": "/value", "mode": "local", "reason": None}
    assert body["expressions"] == [expression]


async def test_only_this_workflows_versions_are_read(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        a = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "A", "draft": GRAPH})).json()
        b = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "B", "draft": GRAPH})).json()
        va = (await c.post(f"/api/v1/t/{tid}/workflows/{a['id']}/publish", headers={"If-Match": "1"})).json()
        wrong = await c.get(f"/api/v1/t/{tid}/workflows/{b['id']}/versions/{va['version_id']}")
        missing = await c.get(f"/api/v1/t/{tid}/workflows/{a['id']}/versions/{uuid.uuid4()}")
    assert (wrong.status_code, wrong.json()) == (404, {"error": "not_found"})
    assert missing.status_code == 404
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, tid, "viewer")
    async with viewer:
        assert (await viewer.get(f"/api/v1/t/{tid}/workflows/{a['id']}/versions/{va['version_id']}")).status_code == 200
    stranger, other = await session_client(app, owner_sessionmaker, api_settings, "owner")
    async with stranger:
        path = f"/api/v1/t/{other}/workflows/{a['id']}/versions/{va['version_id']}"
        assert (await stranger.get(path)).status_code == 404


async def new_workflow(c, tid) -> str:
    name = f"W {uuid.uuid4().hex[:6]}"
    wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": name, "draft": GRAPH})).json()
    return f"/api/v1/t/{tid}/workflows/{wf['id']}"


async def test_publish_names_the_version_it_expects(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await new_workflow(c, tid)
        first = await c.post(f"{base}/publish", headers={"If-Match": "1"}, json={"expected_latest_version": 0})
        assert (first.status_code, first.json()["number"]) == (201, 1)
        stale = await c.post(f"{base}/publish", headers={"If-Match": "1"}, json={"expected_latest_version": 0})
        assert (stale.status_code, stale.json()) == (409, {"error": "version_changed", "latest_version": 1})
        assert [v["number"] for v in (await c.get(f"{base}/versions")).json()] == [1]  # nothing published
        second = await c.post(f"{base}/publish", headers={"If-Match": "1"}, json={"expected_latest_version": 1})
        assert (second.status_code, second.json()["number"]) == (201, 2)


@pytest.mark.parametrize("body", [None, {}, {"expected_latest_version": None}])
async def test_publish_without_an_expectation_behaves_as_before(app, owner_sessionmaker, api_settings, body) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await new_workflow(c, tid)
        await c.post(f"{base}/publish", headers={"If-Match": "1"})
        r = await c.post(f"{base}/publish", headers={"If-Match": "1"}, **({} if body is None else {"json": body}))
    assert (r.status_code, r.json()["number"]) == (201, 2)


@pytest.mark.parametrize(
    "body",
    [
        {"expected_latest_version": -1},
        {"expected_latest": 1},
        {"expected_latest_version": "1"},
        {"expected_latest_version": 1.0},
        {"expected_latest_version": True},
    ],
)
async def test_a_malformed_expectation_is_refused(app, owner_sessionmaker, api_settings, body) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await new_workflow(c, tid)
        r = await c.post(f"{base}/publish", headers={"If-Match": "1"}, json=body)
        assert (await c.get(f"{base}/versions")).json() == []
    assert r.status_code == 422 and r.json()["error"] == "invalid"


async def test_a_draft_conflict_is_answered_before_a_version_change(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await new_workflow(c, tid)
        await c.post(f"{base}/publish", headers={"If-Match": "1"})
        r = await c.post(f"{base}/publish", headers={"If-Match": "7"}, json={"expected_latest_version": 0})
    assert (r.status_code, r.json()) == (409, {"error": "draft_conflict", "draft_revision": 1})


async def test_two_publishers_naming_one_version_publish_it_once(app, owner_sessionmaker, api_settings) -> None:
    """The expectation is checked under the lock that numbers the version: of two editors who both saw version 1, one
    publishes version 2 and the other is told, never silently publishing version 3."""
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await new_workflow(c, tid)
        await c.post(f"{base}/publish", headers={"If-Match": "1"})
        ask = {"headers": {"If-Match": "1"}, "json": {"expected_latest_version": 1}}
        both = await asyncio.gather(*(c.post(f"{base}/publish", **ask) for _ in range(2)))
        numbers = [v["number"] for v in (await c.get(f"{base}/versions")).json()]
    assert sorted(r.status_code for r in both) == [201, 409]
    assert next(r for r in both if r.status_code == 409).json() == {"error": "version_changed", "latest_version": 2}
    assert numbers == [2, 1]
