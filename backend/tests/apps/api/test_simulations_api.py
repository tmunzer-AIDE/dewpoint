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
from tests.apps.test_admission_drafts import LOOP_GRAPH, STEPS_GRAPH, drafted
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
