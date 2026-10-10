# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Any

import pytest

from dewpoint.core.plugins import lifecycle
from dewpoint.core.plugins.lifecycle import Entry
from dewpoint.engine.graph.model import graph_hash, parse_graph
from tests.apps.api.helpers import member_client, session_client
from tests.support.graphs import G, cel, nid, ref
from tests.support.registry import sync_test_plugins

GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data()


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


async def test_draft_edit_validate_publish_flow(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        r = await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Nightly"})
        assert r.status_code == 201, r.text
        wf = r.json()
        base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
        assert wf["draft_revision"] == 1 and wf["active_version_id"] is None and wf["executable"] is None
        assert (await c.put(f"{base}/draft", json=GRAPH)).status_code == 428
        stale = await c.put(f"{base}/draft", json=GRAPH, headers={"If-Match": "7"})
        assert stale.status_code == 409 and stale.json() == {"error": "draft_conflict", "draft_revision": 1}
        saved = await c.put(f"{base}/draft", json=GRAPH, headers={"If-Match": "1"})
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert (body["draft_revision"], body["unpublished_changes"], body["active_version_id"]) == (2, True, None)
        assert body["graph_hash"] == graph_hash(parse_graph(GRAPH))
        checked = (await c.post(f"{base}/validate")).json()
        assert checked["valid"] is True and checked["diagnostics"] == []
        published = await c.post(f"{base}/publish", headers={"If-Match": '"2"'})
        assert published.status_code == 201, published.text
        assert published.json()["number"] == 1
        got = (await c.get(base)).json()
        assert got["active_version_number"] == 1 and got["executable"] is True
        assert got["draft"]["nodes"][0]["key"] == "a"
        versions = (await c.get(f"{base}/versions")).json()
        assert [(v["number"], v["active"], v["executable"]) for v in versions] == [(1, True, True)]
        actions = [e["action"] for e in (await c.get(f"/api/v1/t/{tid}/audit")).json()]
    assert actions[:2] == ["workflow.publish", "workflow.create"]


async def test_publish_and_draft_report_diagnostics(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        bad = G().node("a", "testkit.echo@1", {"value": ref("steps.nope.output")}).data()
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Bad", "draft": bad})).json()
        base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
        r = await c.post(f"{base}/publish", headers={"If-Match": "1"})
        assert r.status_code == 422
        assert r.json()["error"] == "invalid" and [d["code"] for d in r.json()["diagnostics"]] == ["ref.unknown_step"]
        malformed = await c.put(f"{base}/draft", json={"nodes": [{"key": "Bad Key"}]}, headers={"If-Match": "1"})
        assert malformed.status_code == 422 and malformed.json()["diagnostics"][0]["code"] == "graph.format"


async def test_activate_rolls_back(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "W", "draft": GRAPH})).json()
        base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
        v1 = (await c.post(f"{base}/publish", headers={"If-Match": "1"})).json()
        other = G().node("s", "testkit.sensitive@1").data()
        assert (await c.put(f"{base}/draft", json=other, headers={"If-Match": "1"})).status_code == 200
        v2 = (await c.post(f"{base}/publish", headers={"If-Match": "2"})).json()
        assert v2["number"] == 2
        r = await c.post(f"{base}/activate", json={"version_id": v1["version_id"]})
        assert r.status_code == 200 and r.json()["number"] == 1
        assert (await c.get(base)).json()["active_version_number"] == 1
        missing = await c.post(f"{base}/activate", json={"version_id": str(uuid.uuid4())})
        assert missing.status_code == 404


async def test_permission_matrix(app, owner_sessionmaker, api_settings) -> None:
    editor, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with editor:
        wf = (await editor.post(f"/api/v1/t/{tid}/workflows", json={"name": "W", "draft": GRAPH})).json()
    base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
    for role in ("viewer", "operator"):
        c, _ = await member_client(app, owner_sessionmaker, api_settings, tid, role)
        async with c:
            assert (await c.get(base)).status_code == 200
            assert (await c.get(f"{base}/versions")).status_code == 200
            assert (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": role})).status_code == 403
            assert (await c.put(f"{base}/draft", json=GRAPH, headers={"If-Match": "1"})).status_code == 403
            assert (await c.post(f"{base}/validate")).status_code == 403
            assert (await c.post(f"{base}/publish", headers={"If-Match": "1"})).status_code == 403
            assert (await c.patch(base, json={"enabled": False})).status_code == 403
    stranger, other_tenant = await session_client(app, owner_sessionmaker, api_settings, "owner")
    async with stranger:
        assert (await stranger.get(f"/api/v1/t/{other_tenant}/workflows/{wf['id']}")).status_code == 404
        assert (await stranger.get(base)).status_code == 404


async def test_disable_and_rename(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        a = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "A"})).json()
        await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "B"})
        r = await c.patch(f"/api/v1/t/{tid}/workflows/{a['id']}", json={"enabled": False, "name": "Renamed"})
        assert r.status_code == 200 and r.json()["enabled"] is False and r.json()["name"] == "Renamed"
        taken = await c.patch(f"/api/v1/t/{tid}/workflows/{a['id']}", json={"name": "B"})
        assert taken.status_code == 409 and taken.json() == {"error": "name_taken"}


async def test_reenabling_a_blocked_workflow_is_refused(
    app, owner_sessionmaker, api_settings, admin_sessionmaker
) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "W", "draft": GRAPH})).json()
        base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
        assert (await c.post(f"{base}/publish", headers={"If-Match": "1"})).status_code == 201
        assert (await c.patch(base, json={"enabled": False})).json()["enabled"] is False
        async with admin_sessionmaker() as s, s.begin():
            assert (await lifecycle.retire(s, Entry("node", "testkit.echo@1"))).applied  # its only user is disabled
        r = await c.patch(base, json={"enabled": True})
        assert r.status_code == 422 and r.json()["error"] == "not_enableable"
        assert [d["code"] for d in r.json()["diagnostics"]] == ["lifecycle.retired"]
        assert (await c.get(base)).json()["enabled"] is False


async def test_oversized_draft_is_rejected(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "W"})).json()
        huge = {"graph_format": 1, "settings": {"outputs": {"x": "a" * (1024 * 1024)}}}
        r = await c.put(f"/api/v1/t/{tid}/workflows/{wf['id']}/draft", json=huge, headers={"If-Match": "1"})
        assert r.status_code == 413 and r.json() == {"error": "too_large"}


async def test_node_types_catalog(app, owner_sessionmaker, api_settings, admin_sessionmaker) -> None:
    async with admin_sessionmaker() as s, s.begin():
        await lifecycle.deprecate(s, Entry("node", "testkit.slow@1"), actor_id=None)
        await lifecycle.retire(s, Entry("node", "testkit.fail_n@1"))
    c, _ = await session_client(app, owner_sessionmaker, api_settings, "viewer")
    async with c:
        types = {t["ref"]: t for t in (await c.get("/api/v1/node-types")).json()}
    assert types["flow.if@1"]["ports"] == ["true", "false"] and types["testkit.echo@1"]["state"] == "active"
    assert types["testkit.slow@1"]["state"] == "deprecated" and "testkit.fail_n@1" not in types


async def test_oversized_drafts_are_rejected_without_a_trustworthy_length(
    app, owner_sessionmaker, api_settings
) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "W"})).json()
        base = f"/api/v1/t/{tid}/workflows/{wf['id']}"

        async def chunks():  # type: ignore[no-untyped-def]  # an async body is sent chunked: no Content-Length
            yield b'{"graph_format": 1, "settings": {"outputs": {"x": "'
            for _ in range(20):
                yield b"a" * 65_536
            yield b'"}}}'

        r = await c.put(
            f"{base}/draft", content=chunks(), headers={"If-Match": "1", "Content-Type": "application/json"}
        )
        assert r.status_code == 413 and r.json() == {"error": "too_large"}
        assert (await c.get(base)).json()["draft_revision"] == 1


async def test_non_finite_numbers_are_a_format_error_not_a_server_error(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "W"})).json()
        url = f"/api/v1/t/{tid}/workflows/{wf['id']}/draft"
        headers = {"If-Match": "1", "Content-Type": "application/json"}
        node = f'{{"id": "{uuid.uuid4()}", "key": "a", "type": "testkit.echo@1", "position": {{"x": 1e400, "y": 0}}}}'
        huge = await c.put(url, content=f'{{"graph_format": 1, "nodes": [{node}]}}'.encode(), headers=headers)
        nan = await c.put(url, content=b'{"graph_format": 1, "settings": {"outputs": {"x": NaN}}}', headers=headers)
    for r, field in ((huge, "/nodes/0/position/x"), (nan, "/settings/outputs/x")):
        assert r.status_code == 422, r.text
        assert [(d["code"], d["field"]) for d in r.json()["diagnostics"]] == [("graph.format", field)]


async def test_deeply_nested_drafts_are_refused_before_they_are_stored(app, owner_sessionmaker, api_settings) -> None:
    deep: Any = 1
    for _ in range(300):
        deep = [deep]
    nested_schema: dict[str, Any] = {"type": "string"}
    for _ in range(100):
        nested_schema = {"type": "object", "properties": {"p": nested_schema}}
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        created = await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Deep", "draft": _with_value(deep)})
        assert created.status_code == 422 and created.json()["diagnostics"][0]["code"] == "graph.format"
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "W"})).json()
        base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
        for draft in (_with_value(deep), {"graph_format": 1, "settings": {"input_schema": nested_schema}}):
            r = await c.put(f"{base}/draft", json=draft, headers={"If-Match": "1"})
            assert r.status_code == 422 and r.json()["diagnostics"][0]["code"] == "graph.format"
        got = await c.get(base)
        assert got.status_code == 200 and got.json()["draft_revision"] == 1


def _with_value(value: Any) -> dict[str, Any]:
    return G().node("a", "testkit.echo@1", {"value": value}).data()


async def test_validate_reports_how_each_expression_runs(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    nested = cel("[1, 2].map(x, [1, 2].map(y, x * y))")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "C"})).json()
        base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
        draft = G().node("a", "testkit.echo@1", {"value": nested}).data()
        assert (await c.put(f"{base}/draft", json=draft, headers={"If-Match": "1"})).status_code == 200
        checked = (await c.post(f"{base}/validate")).json()
    assert checked["valid"] is True
    assert [(d["code"], d["severity"]) for d in checked["diagnostics"]] == [("cel.iteration_budget", "warning")]
    assert checked["expressions"] == [
        {"node": str(nid("a")), "field": "/value", "mode": "activity", "reason": "more than one nested loop"}
    ]


async def test_validation_explains_the_taint_to_the_editor(app, owner_sessionmaker, api_settings) -> None:
    """Engine 2b spec §4.1: the editor shows why an expression runs in the evaluator, which values are tainted, and
    what each declassified site reveals."""
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    g = G().node("c", "flow.if@1", {"condition": cel("size(trigger.token) > 8")}).node("a", "testkit.echo@1")
    g.node("b", "testkit.echo@1", {"value": ref("trigger.token")}).edge("c", "a", "true").edge("c", "b", "false")
    g.settings = {
        "input_schema": {
            "type": "object",
            "properties": {"token": {"type": "string", "x-sensitive": True}},
            "required": ["token"],
            "additionalProperties": False,
        },
        "declassify": [{"node": str(nid("c")), "field": "/condition"}],
    }
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Taint", "draft": g.data()})).json()
        checked = (await c.post(f"/api/v1/t/{tid}/workflows/{wf['id']}/validate")).json()
    assert checked["valid"] is True
    assert checked["expressions"] == [
        {"node": str(nid("c")), "field": "/condition", "mode": "activity", "reason": "reads sensitive data"}
    ]
    assert checked["taint"] == {
        "sites": sorted(
            [{"node": str(nid("b")), "field": "/value"}, {"node": str(nid("c")), "field": "/condition"}],
            key=lambda s: s["node"],
        ),
        "declassified": [{"node": str(nid("c")), "field": "/condition", "reveals": "the branch taken"}],
    }


async def test_a_tainted_workflow_output_is_a_site_with_no_step(app, owner_sessionmaker, api_settings) -> None:
    """A workflow output's value belongs to no step: its tainted site says `node: null`, as its expression does,
    whether the output is the value or holds it."""
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    g = G().node("a", "testkit.echo@1")
    g.settings = {
        "input_schema": {
            "type": "object",
            "properties": {"token": {"type": "string", "x-sensitive": True}},
            "required": ["token"],
            "additionalProperties": False,
        },
        "outputs": {"echo": ref("trigger.token"), "pair": {"secret": ref("trigger.token"), "plain": 1}},
    }
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Out", "draft": g.data()})).json()
        r = await c.post(f"/api/v1/t/{tid}/workflows/{wf['id']}/validate")
    assert r.status_code == 200, r.text
    assert r.json()["valid"] is True
    assert r.json()["taint"] == {
        "sites": [
            {"node": None, "field": "/settings/outputs/echo"},
            {"node": None, "field": "/settings/outputs/pair/secret"},
        ],
        "declassified": [],
    }


async def test_validate_says_which_steps_may_not_run(app, owner_sessionmaker, api_settings) -> None:
    """4c-2a ruling 3: a branch's steps may not run; the step after the join does."""
    draft = (
        G().node("c", "flow.if@1", {"condition": True})
        .node("t", "testkit.echo@1", {"value": 1}).node("f", "testkit.echo@1", {"value": 2})
        .node("j", "testkit.echo@1", {"value": 3})
        .edge("c", "t", port="true").edge("c", "f", port="false").edge("t", "j").edge("f", "j")
        .data()
    )  # fmt: skip
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Branches", "draft": draft})).json()
        r = await c.post(f"/api/v1/t/{tid}/workflows/{wf['id']}/validate")
    assert r.status_code == 200, r.text
    assert r.json()["conditional_steps"] == sorted([str(nid("t")), str(nid("f"))])
