# SPDX-License-Identifier: Apache-2.0
"""The editor's data routes (B6, B7; 4c-2a rulings 4–10): what a field can read, and a step's newest sample."""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from tests.apps.api.helpers import member_client, session_client
from tests.support.graphs import G, nid
from tests.support.registry import sync_test_plugins
from tests.support.workflows import PROFILE

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


async def _sampled(owner: Any, base: str, step: uuid.UUID, *, mode: str = "live", output: Any = None) -> str:
    """Publish isn't needed: a version row (as `tests/support/connections.py::seed_step` writes one, from the draft)
    and an ended run with a succeeded row for `step`."""
    tenant, workflow_id = base.split("/")[4], base.split("/")[6]
    version, run = uuid.uuid4(), uuid.uuid4()
    async with owner() as s, s.begin():
        draft = (await s.execute(text("select draft from workflows where id = :w"), {"w": workflow_id})).scalar_one()
        await s.execute(text("insert into cel_profiles(profile) values (:p) on conflict do nothing"), {"p": PROFILE})
        await s.execute(
            text(
                "insert into workflow_versions(id,tenant_id,workflow_id,number,graph,node_refs,engine_abi,cel_profile,"
                "input_schema,output_schema,vars_schema,closure_version_ids,closure_workflow_ids,closure_node_refs,"
                "closure_cel_profiles,closure_depth,graph_hash,version_hash,connection_ids) "
                "values (:v,:t,:w,1,cast(:g as jsonb),array['testkit.echo@1'],1,cast(:p as text),"
                "'{}','{}','{}',array[cast(:v as uuid)],array[cast(:w as uuid)],array['testkit.echo@1'],"
                "array[cast(:p as text)],0,'h','h','{}')"
            ),
            {"v": version, "t": tenant, "w": workflow_id, "g": json.dumps(draft), "p": PROFILE},
        )
        await s.execute(
            text("insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, ended_at) "
                 "values (:r, :t, :w, :v, :m, 'succeeded', now())"),
            {"r": run, "t": tenant, "w": workflow_id, "v": version, "m": mode},
        )  # fmt: skip
        await s.execute(
            text("insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status, "
                 "ended_at, output_preview) values (:t, :r, :s, '', 1, 'a', 'succeeded', now(), cast(:o as jsonb))"),
            {"t": tenant, "r": run, "s": step, "o": json.dumps(output if output is not None else {"value": 1})},
        )  # fmt: skip
    return str(run)


async def test_answers_a_steps_newest_sample(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await _create(c, tid)
        run = await _sampled(owner_sessionmaker, base, nid("a"), output={"value": "[redacted]"})
        r = await c.get(f"{base}/draft/samples", params={"node": str(nid("a"))})
    assert r.status_code == 200, r.text
    sample = r.json()["sample"]
    assert (sample["run_id"], sample["mode"], sample["version_number"], sample["attempt"]) == (run, "live", 1, 1)
    assert sample["output"] == {"value": "[redacted]"}  # as stored: the API never unmasks
    assert (sample["type"], sample["same_type"], sample["same_config"], sample["stale"]) == (
        "testkit.echo@1",
        True,
        True,
        False,
    )
    assert sample["connections"] == {"state": "none", "items": []}  # an echo names no connection


async def test_marks_a_sample_stale_when_the_config_differs(app, owner_sessionmaker, api_settings) -> None:
    changed = G().node("a", "testkit.echo@1", {"value": 2}).node("c", "flow.if@1", {"condition": True}).edge("a", "c")
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await _create(c, tid)
        await _sampled(owner_sessionmaker, base, nid("a"))
        assert (await c.put(f"{base}/draft", json=changed.data(), headers={"If-Match": "1"})).status_code == 200
        r = await c.get(f"{base}/draft/samples", params={"node": str(nid("a"))})
    sample = r.json()["sample"]
    assert r.json()["draft_revision"] == 2 and not sample["same_config"] and sample["stale"]


async def test_says_a_simulated_sample_used_no_connection(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await _create(c, tid)
        await _sampled(owner_sessionmaker, base, nid("a"), mode="simulate")
        sample = (await c.get(f"{base}/draft/samples", params={"node": str(nid("a"))})).json()["sample"]
    assert sample["mode"] == "simulate" and sample["connections"]["state"] == "simulated"


async def test_has_no_sample_for_a_step_without_one(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await _create(c, tid)
        none_yet = await c.get(f"{base}/draft/samples", params={"node": str(nid("a"))})
        not_there = await c.get(f"{base}/draft/samples", params={"node": str(uuid.uuid4())})
    assert none_yet.json()["sample"] is None and not_there.json()["sample"] is None
    assert (none_yet.json()["searched_runs"], none_yet.json()["search_limit"]) == (0, 200)  # no run yet: none searched


def test_tells_the_four_connection_states() -> None:
    from datetime import UTC, datetime

    from dewpoint.apps.workflow_ops import sample_answer
    from dewpoint.core.runs.samples import Sample, UsedConnection

    step = {"id": "x", "type": "testkit.http_call@1", "config": {"connection": "c1"}}
    base = dict(run_id=uuid.uuid4(), run_kind="run", mode="live", version_id=uuid.uuid4(), version_number=1,
                iteration_key="", attempt=1, captured_at=datetime.now(UTC), output={}, node=step)  # fmt: skip
    used = UsedConnection(uuid.uuid4(), "testkit", "Lab", 1, 2, {})
    cases = {
        "recorded": Sample(**base, connections=(used,), names_connection=True),
        "unknown": Sample(**base, connections=(), names_connection=True),
        "none": Sample(**base, connections=(), names_connection=False),
    }
    for state, sample in cases.items():
        assert sample_answer(sample, step)["connections"]["state"] == state  # type: ignore[index]
    assert sample_answer(cases["recorded"], step)["stale"]  # its connection changed since
    simulated = Sample(**{**base, "mode": "simulate"}, connections=(), names_connection=True)
    assert sample_answer(simulated, step)["connections"]["state"] == "simulated"  # type: ignore[index]
