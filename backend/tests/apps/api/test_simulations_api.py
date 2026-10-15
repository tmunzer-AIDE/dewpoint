# SPDX-License-Identifier: Apache-2.0
"""Simulating a draft through the API (B8; the simulation design §6.3): `POST …/draft/simulations` with `If-Match` (the
draft revision) and an `Idempotency-Key`, `{input}` for the workflow or `{target}` for a step alone (S2). It needs
`workflow.edit` and `run.start`, answers 202 with the request, and refuses in the server's words: 409 for another
revision, 422 for a draft that can't run, for seeds, and for a step that can't run alone."""

import uuid
from typing import Any

import pytest

from tests.apps.api.test_run_requests_api import as_role, keyed_app
from tests.apps.test_admission import current
from tests.apps.test_admission_drafts import LOOP_GRAPH, STEPS_GRAPH, drafted, simulate
from tests.apps.test_workflow_ops import create, save
from tests.support.graphs import G, nid

pytestmark = pytest.mark.usefixtures("development_deployment")
__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys


def url(ctx: Any, wf: uuid.UUID) -> str:
    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/draft/simulations"


def headers(key: str = "k1", revision: int | str | None = 1) -> dict[str, str]:
    return {"Idempotency-Key": key} | ({} if revision is None else {"If-Match": f'"{revision}"'})


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker) -> Any:
    await current(dispatch_sessionmaker)
    return await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, STEPS_GRAPH)


async def test_an_editor_simulates_the_draft_and_gets_its_queued_request(
    keyed_app, ready, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await client.post(url(ctx, wf), json={"input": {}}, headers=headers())
    assert answer.status_code == 202, answer.text
    body = answer.json()
    assert {k: body[k] for k in ("status", "mode", "source", "version_id", "draft_revision", "target_step_id",
                                 "admission_checks")} == {
        "status": "queued", "mode": "simulate", "source": "manual", "version_id": None, "draft_revision": 1,
        "target_step_id": None, "admission_checks": [],
    }  # fmt: skip
    assert body["draft_snapshot_id"] and body["workflow_id"] == str(wf)
    again = await client.post(url(ctx, wf), json={"input": {}}, headers=headers())
    assert (again.status_code, again.json()["id"]) == (202, body["id"])  # an exact retry


@pytest.mark.parametrize(("role", "status"), [("viewer", 403), ("operator", 403), ("editor", 202), ("admin", 202)])
async def test_simulating_needs_workflow_edit_and_run_start(
    keyed_app, ready, owner_sessionmaker, api_settings, role, status
) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, role)
    answer = await client.post(url(ctx, wf), json={"input": {}}, headers=headers())
    assert answer.status_code == status, answer.text


async def test_the_revision_and_the_key_are_required(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    for sent, status, code in (
        ({"Idempotency-Key": "k1"}, 428, "revision_required"),
        (headers(revision="x"), 400, "bad_revision"),
        ({"If-Match": "1"}, 428, "idempotency_key_required"),
    ):
        answer = await client.post(url(ctx, wf), json={"input": {}}, headers=sent)
        assert (answer.status_code, answer.json()["error"]) == (status, code)


async def test_another_revision_is_a_conflict_naming_the_drafts(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    await save(api_sessionmaker, ctx, wf, STEPS_GRAPH)
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await client.post(url(ctx, wf), json={"input": {}}, headers=headers(revision=1))
    assert (answer.status_code, answer.json()) == (409, {"error": "draft_conflict", "draft_revision": 2})


async def test_a_draft_that_cant_run_seeds_and_targets_are_refused_in_the_servers_words(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    missing = await client.post(url(ctx, wf), json={"target": {"step_id": str(nid("b"))}}, headers=headers("k1"))
    assert missing.status_code == 422
    assert missing.json() == {"error": "seed_missing", "problems": [{
        "code": "seed_missing", "pointer": "/steps/a/output/value",
        "message": "Give this value, or leave it absent if it may be.",
    }]}  # fmt: skip
    alone = await client.post(url(ctx, wf), json={"target": {"step_id": str(uuid.uuid4())}}, headers=headers("k2"))
    assert (alone.status_code, alone.json()["error"]) == (422, "target_invalid")
    both = await client.post(url(ctx, wf), json={"input": {"x": 1}, "target": {"step_id": str(nid("b"))}},
                             headers=headers("k3"))  # fmt: skip
    assert both.status_code == 422
    broken = await create(api_sessionmaker, ctx, G().node("z", "no.such@1").data(), name="broken")
    invalid = await client.post(url(ctx, broken), json={"input": {}}, headers=headers("k4"))
    assert (invalid.status_code, invalid.json()["error"]) == (422, "invalid")
    assert [d["code"] for d in invalid.json()["diagnostics"]] == ["node.unknown_type"]
    looped = await create(api_sessionmaker, ctx, LOOP_GRAPH, name="looped")
    loop = await client.post(url(ctx, looped), json={"target": {"step_id": str(nid("l"))}}, headers=headers("k5"))
    assert (loop.status_code, loop.json()["error"]) == (422, "target_invalid")


async def test_re_running_a_draft_run_or_a_published_child_of_one_is_refused(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Spec §6.5: a draft run is never run again, on the published version or otherwise: simulate the draft again."""
    from sqlalchemy import text

    from tests.apps.test_admission import published
    from tests.core.retention.support import RECENT, snapshot, tree

    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    async with owner_sessionmaker() as s:
        active = (await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})).scalar()
    rows = {"t": ctx.tenant_id, "w": wf, "v": active, "u": ctx.user.id}
    ran = await tree(owner_sessionmaker, rows, RECENT, snapshot=await snapshot(owner_sessionmaker, rows))
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "operator")
    for n, run_id in enumerate((ran["root"], ran["sub"])):
        answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}/rerun", json={},
                                   headers={"Idempotency-Key": f"r{n}"})  # fmt: skip
        assert (answer.status_code, answer.json()["error"]) == (409, "draft_run")


async def test_the_runs_api_shows_a_draft_runs_snapshot_target_and_each_steps_effect(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Spec §6.5: a draft run, queued or started, names its snapshot and its target, and no version (D-b3: readable
    with `run.view`); a step shows what it did besides its output (4d-1a's `effect_preview`)."""
    from sqlalchemy import text

    from tests.apps.dispatcher.support import begin, workers

    ctx, wf = ready
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
                              values={"/steps/a/output/value": 5})).request  # fmt: skip
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    shown = {k: v for k, v in (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")).json()[0].items()
             if k in ("id", "version_id", "draft_snapshot_id", "target_step_id")}  # fmt: skip
    assert shown == {"id": str(request.id), "version_id": None, "draft_snapshot_id": str(request.draft_snapshot_id),
                     "target_step_id": str(nid("b"))}  # fmt: skip
    await workers(owner_sessionmaker)
    await begin(dispatch_sessionmaker, request, api_settings)
    async with owner_sessionmaker() as s, s.begin():  # as the worker's projection leaves it
        await s.execute(text("update run_requests set status = 'started' where id = :i"), {"i": request.id})
        await s.execute(text("update runs set started_at = now() where id = :i"), {"i": request.id})
        await s.execute(text("insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, "
                             "status, effect_preview) values (:t, :r, :s, '', 1, 'b', 'succeeded', :e)"),
                        {"t": ctx.tenant_id, "r": request.id, "s": nid("b"), "e": '{"port": "true"}'})  # fmt: skip
    run = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{request.id}")).json()
    assert (run["version_id"], run["draft_snapshot_id"], run["target_step_id"]) == (
        None, str(request.draft_snapshot_id), str(nid("b")),
    )  # fmt: skip
    assert [(step["key"], step["effect"]) for step in run["steps"]] == [("b", {"port": "true"})]


async def test_a_draft_snapshot_is_read_with_its_graph(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    """Spec §6.5: B4a's version read, for a draft run's snapshot (`workflow.view`)."""
    ctx, wf = ready
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings)).request
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    base = f"/api/v1/t/{ctx.tenant_id}/workflows"
    answer = await viewer.get(f"{base}/{wf}/draft/snapshots/{request.draft_snapshot_id}")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["id"], body["draft_revision"]) == (str(request.draft_snapshot_id), 1)
    assert [n["key"] for n in body["graph"]["nodes"]] == ["a", "b"] and body["expressions"] == []
    other = await create(api_sessionmaker, ctx, STEPS_GRAPH, name="other")
    for path in (f"{base}/{other}/draft/snapshots/{request.draft_snapshot_id}",
                 f"{base}/{wf}/draft/snapshots/{uuid.uuid4()}"):  # fmt: skip
        assert (await viewer.get(path)).status_code == 404
