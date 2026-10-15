# SPDX-License-Identifier: Apache-2.0
"""A draft simulation's steps (B8; the simulation design §6.6, §7.4), `run.view`: a summary per step of the draft it
ran (each instance's final attempt counted by status, its ports counted, a single instance's final attempt, the step's
data origin), in run order; and a step's instances, one per iteration, paged and filtered by iteration, in the
iterations' own order."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from tests.apps.api.test_run_requests_api import as_role, keyed_app
from tests.apps.dispatcher.support import begin, workers
from tests.apps.test_admission import current
from tests.apps.test_admission_drafts import STEPS_GRAPH, drafted, simulate
from tests.support.graphs import G, cel, nid

pytestmark = pytest.mark.usefixtures("development_deployment")
__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys

LOOPED = (
    G().node("l", "flow.loop@1", {"items": list(range(12))}).node("c", "flow.if@1", {"condition": True})
    .node("x", "testkit.echo@1", {"value": 1}).node("d", "flow.delay@1", {"duration_s": 1})
    .node("t", "flow.transform@1", {"fields": {"n": cel("1 + 1")}})
    .edge("l", "c", "body").edge("c", "x", "true").data() | {"settings": {"input_schema": {"type": "object"}}}
)  # fmt: skip


def steps(ctx: Any, wf: uuid.UUID, request_id: uuid.UUID, step: str | None = None) -> str:
    base = f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/draft/simulations/{request_id}/steps"
    return base if step is None else f"{base}/{nid(step)}/instances"


async def row(owner: Any, ctx: Any, run_id: uuid.UUID, key: str, iteration: str, attempt: int, status: str, *,
              at: int | None = None, outcome: str | None = None, port: str | None = None) -> None:  # fmt: skip
    """A step row as the worker's projection leaves it: begun `at` seconds into the run (none for an instance that
    never began)."""
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status, "
                 "started_at, ended_at, outcome, effect_preview) values (:t, :r, :s, :i, :a, :k, :st, "
                 "case when cast(:at as integer) is null then null "
                 "else now() - interval '1 hour' + make_interval(secs => cast(:at as integer)) end, "
                 "case when cast(:st as varchar) = 'running' then null else now() end, :o, :e)"),
            {"t": ctx.tenant_id, "r": run_id, "s": nid(key), "i": iteration, "a": attempt, "k": key, "st": status,
             "at": at, "o": outcome, "e": None if port is None else f'{{"port": "{port}"}}'},
        )  # fmt: skip


async def ended(owner: Any, run_id: uuid.UUID, status: str = "succeeded", error_code: str | None = None) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("update runs set status = :s, ended_at = now(), error_code = :e, error_message = :m "
                             "where id = :i"),
                        {"i": run_id, "s": status, "e": error_code, "m": error_code and "m"})  # fmt: skip


@pytest.fixture
async def looped(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    """A simulation of LOOPED, its run row written by dispatch, still running, with no step rows yet."""
    await current(dispatch_sessionmaker)
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, LOOPED)
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings)).request
    await workers(owner_sessionmaker)
    await begin(dispatch_sessionmaker, request, api_settings)
    return ctx, wf, request.id


async def ran_loop(owner: Any, ctx: Any, run_id: uuid.UUID) -> None:
    """The loop's 12 iterations: `c` took `true` 3 times; `x` failed twice (its first instance once, then succeeded on
    its retry) and was skipped 9 times; `d` wasn't waited; `t` never ran."""
    await row(owner, ctx, run_id, "l", "", 1, "succeeded", at=1)
    for i in range(12):
        await row(owner, ctx, run_id, "c", f"l:{i}", 1, "succeeded", at=2, port="true" if i < 3 else "false")
    await row(owner, ctx, run_id, "x", "l:0", 1, "failed", at=3)
    await row(owner, ctx, run_id, "x", "l:0", 2, "succeeded", at=4, outcome="simulated")
    for i in (1, 2):
        await row(owner, ctx, run_id, "x", f"l:{i}", 1, "failed", at=3, outcome="simulated")
    for i in range(3, 12):
        await row(owner, ctx, run_id, "x", f"l:{i}", 1, "skipped")
    await row(owner, ctx, run_id, "d", "", 1, "succeeded", at=5, outcome="simulated")
    await ended(owner, run_id)


async def test_the_summary_counts_each_steps_instances_and_ports_and_says_where_its_data_came_from(
    keyed_app, looped, owner_sessionmaker, api_settings
) -> None:
    ctx, wf, run_id = looped
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    before = (await viewer.get(steps(ctx, wf, run_id))).json()
    assert before["given"] == "input"
    assert {s["key"]: s["origin"] for s in before["steps"]} == dict.fromkeys("lcxdt", "not_reached_yet")
    await ran_loop(owner_sessionmaker, ctx, run_id)
    summary = (await viewer.get(steps(ctx, wf, run_id))).json()
    shown = [(s["key"], s["origin"], s["instances"], s["statuses"], s["ports"]) for s in summary["steps"]]
    assert shown == [  # in run order; a step that never ran last
        ("l", "evaluated", 1, {"succeeded": 1}, {}),
        ("c", "evaluated", 12, {"succeeded": 12}, {"true": 3, "false": 9}),
        ("x", "fixture_not_sent", 12, {"succeeded": 1, "failed": 2, "skipped": 9}, {}),
        ("d", "evaluated_not_waited", 1, {"succeeded": 1}, {}),
        ("t", "didnt_run", 0, {}, {}),
    ]
    final = {s["key"]: s["final"] for s in summary["steps"]}
    assert final["c"] is None and final["x"] is None and final["t"] is None  # many instances, or none
    assert (final["d"]["attempt"], final["d"]["status"], final["d"]["outcome"]) == (1, "succeeded", "simulated")


async def test_a_step_with_no_row_is_not_recorded_when_the_run_ended_outside_the_workflow(
    keyed_app, looped, owner_sessionmaker, api_settings
) -> None:
    """D-a5: a bug, a termination or a lost history ended it: what it would have recorded is unknown."""
    ctx, wf, run_id = looped
    await row(owner_sessionmaker, ctx, run_id, "l", "", 1, "running", at=1)
    await ended(owner_sessionmaker, run_id, "failed", "internal_error")
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    summary = (await viewer.get(steps(ctx, wf, run_id))).json()
    assert {s["key"]: s["origin"] for s in summary["steps"]} == {"l": "evaluated"} | dict.fromkeys(
        "cxdt", "not_recorded"
    )


async def test_a_steps_instances_are_paged_in_iteration_order_each_its_final_attempt(
    keyed_app, looped, owner_sessionmaker, api_settings
) -> None:
    ctx, wf, run_id = looped
    await ran_loop(owner_sessionmaker, ctx, run_id)
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    first = (await viewer.get(steps(ctx, wf, run_id, "x"), params={"limit": 4})).json()
    assert first["total"] == 12
    assert [(i["iteration_key"], i["attempt"], i["status"]) for i in first["items"]] == [
        ("l:0", 2, "succeeded"), ("l:1", 1, "failed"), ("l:2", 1, "failed"), ("l:3", 1, "skipped"),
    ]  # fmt: skip
    last = (await viewer.get(steps(ctx, wf, run_id, "x"), params={"offset": 8, "limit": 4})).json()
    assert [i["iteration_key"] for i in last["items"]] == ["l:8", "l:9", "l:10", "l:11"]  # by number, not by text
    one = (await viewer.get(steps(ctx, wf, run_id, "x"), params={"within": "l:1"})).json()
    assert (one["total"], [i["iteration_key"] for i in one["items"]]) == (1, ["l:1"])  # never l:10 or l:11


async def test_a_step_test_shows_its_target_alone_and_its_values_as_seeded(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """§7.3: only the target carries a result; the other steps are outside the test."""
    await current(dispatch_sessionmaker)
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, STEPS_GRAPH)
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
                              values={"/steps/a/output/value": 5})).request  # fmt: skip
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    summary = (await viewer.get(steps(ctx, wf, request.id))).json()
    assert summary["given"] == "seeded"
    assert [(s["key"], s["origin"]) for s in summary["steps"]] == [("b", "not_reached_yet")]


async def test_another_workflows_simulation_or_a_step_outside_the_draft_is_not_found(
    keyed_app, looped, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    from tests.apps.test_workflow_ops import create

    ctx, wf, run_id = looped
    other = await create(api_sessionmaker, ctx, LOOPED, name="other")
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    for path in (steps(ctx, other, run_id), steps(ctx, wf, run_id, "nowhere"), steps(ctx, other, run_id, "x")):
        assert (await viewer.get(path)).status_code == 404, path
