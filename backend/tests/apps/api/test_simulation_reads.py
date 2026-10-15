# SPDX-License-Identifier: Apache-2.0
"""A draft simulation's reads (B8; the simulation design §6.6), `run.view` (D-b3): the person's latest simulations of a
workflow, newest first, labelled with their revision; a simulation's state, a requested cancel included; the input or
seeds it used, read back from its own request, redacted, never recomputed from the draft as it is now."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from tests.apps.api.test_run_requests_api import as_role, keyed_app
from tests.apps.dispatcher.support import begin, workers
from tests.apps.test_admission import TOKEN, TOKEN_GRAPH, current
from tests.apps.test_admission_drafts import STEPS_GRAPH, drafted, simulate
from tests.apps.test_workflow_ops import create, save
from tests.support.graphs import nid

pytestmark = pytest.mark.usefixtures("development_deployment")
__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys


def simulations(ctx: Any, wf: uuid.UUID, request_id: uuid.UUID | None = None) -> str:
    base = f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/draft/simulations"
    return base if request_id is None else f"{base}/{request_id}"


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker) -> Any:
    await current(dispatch_sessionmaker)
    return await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, TOKEN_GRAPH)


async def test_a_person_reads_their_own_latest_simulations_of_a_workflow_newest_first(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    me = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    them = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")

    async def post(client: Any, key: str, revision: int, workflow: uuid.UUID = wf) -> str:
        answer = await client.post(simulations(ctx, workflow), json={"input": {"token": TOKEN}},
                                   headers={"Idempotency-Key": key, "If-Match": str(revision)})  # fmt: skip
        assert answer.status_code == 202, answer.text
        return str(answer.json()["id"])

    first = await post(me, "a1", 1)
    await save(api_sessionmaker, ctx, wf, TOKEN_GRAPH)  # revision 2
    second = await post(me, "a2", 2)
    theirs = await post(them, "b1", 2)
    await post(me, "a3", 1, await create(api_sessionmaker, ctx, TOKEN_GRAPH, name="other"))
    listed = (await me.get(simulations(ctx, wf))).json()
    assert [(s["id"], s["draft_revision"]) for s in listed] == [(second, 2), (first, 1)]
    assert [s["id"] for s in (await me.get(simulations(ctx, wf), params={"limit": 1})).json()] == [second]
    assert [s["id"] for s in (await them.get(simulations(ctx, wf))).json()] == [theirs]


async def test_a_simulations_state_says_where_it_is_and_whether_a_cancel_was_requested(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"token": TOKEN, "site": "a"})).request
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    state = (await viewer.get(simulations(ctx, wf, request.id))).json()
    assert (state["request"]["status"], state["run"], state["cancel_requested"]) == ("queued", None, False)
    await workers(owner_sessionmaker)
    await begin(dispatch_sessionmaker, request, api_settings)  # starting: a cancel is only requested
    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "operator")
    cancel = await operator.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request.id}/cancel")
    assert cancel.status_code == 202
    state = (await viewer.get(simulations(ctx, wf, request.id))).json()
    assert (state["request"]["status"], state["cancel_requested"]) == ("starting", True)
    assert state["run"]["status"] == "running"  # the row dispatch wrote before Temporal answered


async def test_the_input_used_is_read_back_redacted_from_the_request_whatever_the_draft_became(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"token": TOKEN, "site": "a"})).request
    await save(api_sessionmaker, ctx, wf, STEPS_GRAPH)  # the draft moves on: the request's own input is read back
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    answer = await viewer.get(simulations(ctx, wf, request.id))
    assert answer.json()["input"] == {"token": "[redacted]", "site": "a"} and answer.json()["seeds"] is None
    assert answer.json()["read_back"] == "kept"
    assert TOKEN not in answer.text


async def test_a_step_tests_seeds_are_read_back_redacted(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    await current(dispatch_sessionmaker)
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, STEPS_GRAPH)
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
                              values={"/steps/a/output/value": 5})).request  # fmt: skip
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    state = (await viewer.get(simulations(ctx, wf, request.id))).json()
    assert state["seeds"] == {"values": {"/steps/a/output/value": "[redacted]"}, "absent": []}  # an echo's: tainted
    assert state["input"] is None


async def test_another_workflows_or_a_published_runs_request_is_not_a_simulation_of_this_one(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"token": TOKEN})).request
    other = await create(api_sessionmaker, ctx, TOKEN_GRAPH, name="other")
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    for path in (simulations(ctx, other, request.id), simulations(ctx, wf, uuid.uuid4())):
        assert (await viewer.get(path)).status_code == 404


async def test_the_simulations_of_a_workflow_the_tenant_doesnt_have_are_not_found(
    keyed_app, ready, owner_sessionmaker, api_settings
) -> None:
    ctx, _ = ready
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    answer = await viewer.get(simulations(ctx, uuid.uuid4()))
    assert (answer.status_code, answer.json()) == (404, {"error": "not_found"})


async def test_an_input_that_doesnt_open_is_said_unreadable_never_read_as_absent(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    """Its ciphertext corrupted: the state still answers, its read-back marked `unreadable`, nothing shown."""
    ctx, wf = ready
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"token": TOKEN, "site": "a"})).request
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_inputs set ciphertext = :junk "
                             "where id = (select envelope_id from run_requests where id = :r)"),
                        {"junk": b"\x00" * 48, "r": request.id})  # fmt: skip
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    answer = await viewer.get(simulations(ctx, wf, request.id))
    assert answer.status_code == 200, answer.text
    state = answer.json()
    assert (state["read_back"], state["input"], state["seeds"]) == ("unreadable", None, None)
    assert state["request"]["id"] == str(request.id)
