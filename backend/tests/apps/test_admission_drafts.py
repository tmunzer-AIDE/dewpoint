# SPDX-License-Identifier: Apache-2.0
"""A draft simulation's admission (B8; the simulation design §6.3): frozen on a snapshot of the revision it names, of
a workflow never published or disabled; an exact retry is the original request whatever the draft became; what can't
run blocks it, what a simulation never meets is reported and kept; the input checked against the draft's trigger
schema, or a step's seeds against its contract, claimed where sensitive (S2)."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import admission
from dewpoint.apps.inputs import RESERVED_INPUT
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.db import tenant_scope
from dewpoint.core.plugins import lifecycle
from dewpoint.core.workflows import service
from dewpoint.engine import ENGINE_ABI
from tests.apps.test_admission import KEYS, OPEN_GRAPH, TOKEN, TOKEN_GRAPH, current
from tests.apps.test_workflow_ops import ECHO, ECHO_GRAPH, actor, create, save, update
from tests.support.graphs import G, nid, ref
from tests.support.registry import sync_test_plugins

pytestmark = pytest.mark.usefixtures("development_deployment")

STEPS = (
    G().node("a", "testkit.echo@1", {"value": 1}).node("b", "testkit.echo@1", {"value": ref("steps.a.output.value")})
)
STEPS_GRAPH = STEPS.edge("a", "b").data() | {"settings": {"input_schema": {"type": "object"}}}
SENSITIVE_READ = G().node("t", "testkit.echo@1", {"value": ref("trigger.token")}).data() | {
    "settings": {"input_schema": TOKEN_GRAPH["settings"]["input_schema"]}
}
PLAIN_READ = G().node("p", "testkit.echo@1", {"value": ref("trigger.site")}).data() | {
    "settings": {"input_schema": {"type": "object", "properties": {"site": {"type": "string"}}, "required": ["site"]}}
}
LOOP_GRAPH = (
    G().node("l", "flow.loop@1", {"items": [1, 2]}).node("x", "testkit.echo@1", {"value": ref("item")})
    .edge("l", "x", "body").data() | {"settings": {"input_schema": {"type": "object"}}}
)  # fmt: skip


async def drafted(owner: Any, api: Any, admin: Any, graph: Any = OPEN_GRAPH) -> tuple[Any, uuid.UUID]:
    """A workflow with a draft, never published."""
    await sync_test_plugins(admin)
    ctx = await actor(owner)
    return ctx, await create(api, ctx, graph)


async def simulate(api: Any, ctx: Any, wf: uuid.UUID, settings: Any, *, key: str = "s1", revision: int = 1,
                   input: dict[str, Any] | None = None, target: uuid.UUID | None = None,
                   values: dict[str, Any] | None = None, absent: tuple[str, ...] = (),
                   ) -> admission.Admitted:  # fmt: skip
    async with api() as s, s.begin():
        return await admission.admit_draft(
            s, KEYS, ctx, workflow_id=wf, idempotency_key=key, input=input or {},
            simulation=admission.Simulation(revision, target, values or {}, absent), settings=settings,
        )  # fmt: skip


async def envelope(dispatch: Any, ctx: Any, request_id: uuid.UUID) -> Any:
    async with dispatch() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        return await claims.read_envelope(s, ClaimCipher(KEYS), ctx.tenant_id, request_id=request_id)


@pytest.fixture
async def built(dispatch_sessionmaker) -> None:
    await current(dispatch_sessionmaker)


@pytest.mark.usefixtures("built")
async def test_a_draft_is_simulated_on_a_snapshot_of_its_revision_published_or_not(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """D-b1: a workflow never published, or disabled, is simulated: testing before the first publish is the point."""
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker)
    r = (await simulate(api_sessionmaker, ctx, wf, api_settings)).request
    assert (r.status, r.source, r.mode, r.workflow_version_id, r.draft_revision, r.target_step_id) == (
        "queued", "manual", "simulate", None, 1, None,
    )  # fmt: skip
    async with owner_sessionmaker() as s:
        found = text("select workflow_id, draft_revision, created_by, graph_hash from draft_snapshots where id = :i")
        snapshot = (await s.execute(found, {"i": r.draft_snapshot_id})).one()
        details = (await s.execute(text("select details from audit_log where action = 'run.request'"))).scalar_one()
    assert snapshot[:3] == (wf, 1, ctx.user.id)
    assert details == {"workflow_id": str(wf), "source": "manual", "mode": "simulate", "status": "queued",
                       "draft_snapshot_id": str(r.draft_snapshot_id), "draft_revision": 1,
                       "graph_hash": snapshot.graph_hash}  # fmt: skip
    await update(api_sessionmaker, ctx, wf, enabled=False)
    again = await simulate(api_sessionmaker, ctx, wf, api_settings, key="s2")
    assert again.new and again.request.draft_snapshot_id == r.draft_snapshot_id  # the same draft: its snapshot


@pytest.mark.usefixtures("built")
async def test_a_revision_the_draft_moved_past_is_refused(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker)
    await save(api_sessionmaker, ctx, wf, OPEN_GRAPH)
    with pytest.raises(service.DraftConflictError) as refused:
        await simulate(api_sessionmaker, ctx, wf, api_settings, revision=1)
    assert refused.value.current_revision == 2


@pytest.mark.usefixtures("built")
async def test_an_exact_retry_is_the_original_request_whatever_the_draft_became(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """Spec §6.3, step 1: the key first; a retry never rebuilds today's draft, nor meets a later refusal."""
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker)
    first = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"site": "a"})).request
    await save(api_sessionmaker, ctx, wf, G().node("z", "no.such@1").data())  # revision 2: it wouldn't validate
    retry = await simulate(api_sessionmaker, ctx, wf, api_settings, input={"site": "a"})
    assert (retry.new, retry.request.id, retry.request.draft_snapshot_id) == (False, first.id, first.draft_snapshot_id)
    for changed in ({"input": {"site": "b"}}, {"revision": 2}, {"target": nid("a")}):
        with pytest.raises(admission.IdempotencyConflictError):
            await simulate(api_sessionmaker, ctx, wf, api_settings, **{"input": {"site": "a"}, **changed})


@pytest.mark.usefixtures("built")
async def test_what_cant_run_blocks_and_what_a_simulation_never_meets_is_reported(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker,
                            G().node("z", "no.such@1").data())  # fmt: skip
    with pytest.raises(admission.DraftInvalidError) as invalid:
        await simulate(api_sessionmaker, ctx, wf, api_settings)
    assert [d.code for d in invalid.value.blocking] == ["node.unknown_type"]
    echo = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="echo")
    async with admin_sessionmaker() as s, s.begin():
        await lifecycle.deprecate(s, ECHO, actor_id=None)
    r = (await simulate(api_sessionmaker, ctx, echo, api_settings, key="s2")).request
    assert [c["code"] for c in r.admission_checks or []] == ["lifecycle.deprecated"]


@pytest.mark.usefixtures("built")
async def test_the_input_is_checked_against_the_drafts_trigger_schema_and_claimed(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, TOKEN_GRAPH)
    for refused, key in (({"site": "a"}, "s1"), ({"token": TOKEN, "rows": []}, "s2")):
        with pytest.raises(admission.AdmissionRefusedError) as e:
            await simulate(api_sessionmaker, ctx, wf, api_settings, key=key, input=refused)
        assert e.value.reason == "input_invalid"
    assert e.value.messages == [RESERVED_INPUT]
    r = (await simulate(api_sessionmaker, ctx, wf, api_settings, key="s3", input={"token": TOKEN})).request
    assert "$claim" in (await envelope(dispatch_sessionmaker, ctx, r.id))["token"]


async def test_a_simulation_needs_a_current_build_of_its_abi(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker)
    await current(dispatch_sessionmaker, age=timedelta(minutes=5))
    with pytest.raises(admission.AdmissionRefusedError) as e:
        await simulate(api_sessionmaker, ctx, wf, api_settings)
    assert e.value.reason == "no_current_build"
    await current(dispatch_sessionmaker, abi=ENGINE_ABI + 1)
    with pytest.raises(admission.AdmissionRefusedError) as e:
        await simulate(api_sessionmaker, ctx, wf, api_settings)
    assert e.value.reason == "version_unusable"


@pytest.mark.usefixtures("built")
async def test_a_step_is_simulated_alone_with_its_seeds_sensitive_ones_claimed(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """S2 (the simulation design §5.3): a seed is split as the run's input is; one the contract marks sensitive (a
    sensitive input, a tainted step's output) is a handle in the envelope, as the run's own value would be."""
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, PLAIN_READ)
    r = (
        await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("p"), values={"/trigger/site": "a"})
    ).request
    assert (r.target_step_id, r.mode) == (nid("p"), "simulate")
    assert await envelope(dispatch_sessionmaker, ctx, r.id) == {"values": {"/trigger/site": "a"}, "absent": []}
    for n, (graph, target, pointer, value) in enumerate([
        (SENSITIVE_READ, nid("t"), "/trigger/token", TOKEN),
        (STEPS_GRAPH, nid("b"), "/steps/a/output/value", 5),  # an echo's output is tainted
    ]):  # fmt: skip
        other = await create(api_sessionmaker, ctx, graph, name=f"w{n}")
        r = (await simulate(api_sessionmaker, ctx, other, api_settings, key=f"k{n}", target=target,
                            values={pointer: value})).request  # fmt: skip
        assert "$claim" in (await envelope(dispatch_sessionmaker, ctx, r.id))["values"][pointer]


@pytest.mark.usefixtures("built")
async def test_seeds_the_contract_doesnt_take_are_refused_naming_each(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, STEPS_GRAPH)
    cases = [  # (values, absent, the refusal's code, its pointers)
        ({}, (), "seed_missing", ["/steps/a/output/value"]),
        ({"/steps/a/output/value": 5, "/trigger/x": 1}, (), "seed_unknown", ["/trigger/x"]),
        ({"/steps/a/output/value": 5, "/run/id": "r"}, (), "seed_unknown", ["/run/id"]),
    ]
    for n, (values, absent, code, pointers) in enumerate(cases):
        with pytest.raises(admission.SeedsRefusedError) as e:
            await simulate(api_sessionmaker, ctx, wf, api_settings, key=f"k{n}", target=nid("b"), values=values,
                           absent=absent)  # fmt: skip
        assert (e.value.reason, [p.pointer for p in e.value.problems]) == (code, pointers)
    looped = await create(api_sessionmaker, ctx, LOOP_GRAPH, name="loop")
    with pytest.raises(admission.SeedsRefusedError) as e:
        await simulate(api_sessionmaker, ctx, looped, api_settings, key="alias", target=nid("x"),
                       values={"/loops/l/item": 1})  # fmt: skip
    assert e.value.reason == "seed_alias"


@pytest.mark.usefixtures("built")
async def test_a_step_that_cant_run_alone_is_refused(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, LOOP_GRAPH)
    for n, target in enumerate((nid("l"), uuid.uuid4())):  # a loop; no step of the draft
        with pytest.raises(admission.AdmissionRefusedError) as e:
            await simulate(api_sessionmaker, ctx, wf, api_settings, key=f"t{n}", target=target)
        assert e.value.reason == "target_invalid"
