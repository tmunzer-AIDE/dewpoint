# SPDX-License-Identifier: Apache-2.0
"""The editor's data routes (B6, B7; 4c-2a rulings 4–10): what a field can read, and a step's newest sample."""

import uuid
from typing import Any

import pytest

from tests.apps.api.helpers import member_client, session_client
from tests.support.graphs import G, nid
from tests.support.registry import sync_test_plugins

DRAFT = G().node("a", "testkit.echo@1", {"value": 1}).node("c", "flow.if@1", {"condition": True}).edge("a", "c").data()
FIELD = {"node": str(nid("c")), "field": "/condition"}


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


async def _create(c: Any, tid: Any, draft: dict[str, Any] = DRAFT) -> str:
    wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Data", "draft": draft})).json()
    return f"/api/v1/t/{tid}/workflows/{wf['id']}"


async def test_answers_what_a_field_can_read(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        r = await c.get(f"{await _create(c, tid)}/draft/scope", params=FIELD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["draft_revision"], body["state"], body["reason"], body["problem"]) == (1, "ok", None, None)
    value = next(e for e in body["entries"] if e["path"] == "steps.a.output.value")
    assert value["step"] == str(nid("a")) and value["nameable"] and value["types"] == []  # the echo's value: any
    # Data the schema doesn't describe counts as sensitive (engine 2b spec §4.1), so a formula on it would need
    # declassifying; `a` always runs before `c`, so nothing guards it.
    assert value["sensitive"] and value["formula"] == {"guards": [], "sensitive": True, "null_test": True}
    assert next(e for e in body["entries"] if e["path"] == "run.now")["formula"] == {
        "guards": [],
        "sensitive": False,
        "null_test": False,
    }


async def test_a_viewer_reads_the_scope_too(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await _create(c, tid)
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, tid, "viewer")
    async with viewer:
        assert (await viewer.get(f"{base}/draft/scope", params=FIELD)).status_code == 200


async def test_says_why_there_is_no_scope(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        r = await c.get(f"{await _create(c, tid)}/draft/scope", params={**FIELD, "node": str(uuid.uuid4())})
    assert r.status_code == 200 and r.json()["state"] == "unavailable" and r.json()["entries"] == []
    assert r.json()["reason"] == "This step isn't in the saved draft yet."


async def test_answers_the_validators_own_problem_for_a_path(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        r = await c.get(f"{await _create(c, tid)}/draft/scope", params={**FIELD, "at": "steps.nope.output"})
    assert r.status_code == 200 and r.json()["problem"]["code"] == "ref.unknown_step"


async def test_asks_one_question_at_a_time(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await _create(c, tid)
        two = await c.get(f"{base}/draft/scope", params={**FIELD, "under": "steps.a.output", "find": "value"})
        bad = await c.get(f"{base}/draft/scope", params={**FIELD, "field": "condition"})
    assert (two.status_code, two.json()) == (422, {"error": "one_question"})  # the app's error shape: no `detail`
    assert (bad.status_code, bad.json()) == (422, {"error": "invalid_field"})
