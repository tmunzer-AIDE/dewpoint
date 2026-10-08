# SPDX-License-Identifier: Apache-2.0
"""A tenant's next due request in the same cycle (the owner's ruling 1 on 2b-4b's M3 checkpoint: the per-tenant start
path first). A cycle started each tenant's oldest due request, one a cycle: about 0.9 starts a second per tenant on the
dev server, whatever its backlog. After its pick, a cycle now takes again each tenant that has just started one, its
next due request, round after round, while the pass has run less than `AGAIN_S` and its budget lasts: every request
still begun alone (its admission checks, its tenant's slot), each tenant's oldest due first, and each round taking
every such tenant once, so none takes another's turn."""

from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.dispatcher import budget, dispatch
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.dispatcher.support import BUILD, state, workers
from tests.apps.test_admission import KEYS, admit, current, published
from tests.apps.test_runs import FakeClient

pytestmark = pytest.mark.usefixtures("development_deployment")


async def queued(stack: tuple[Any, ...], n: int, limit: int | None = None) -> tuple[Any, list[Any]]:
    """A tenant with `n` requests queued in order (and a run limit, if any)."""
    owner, api, admin, settings = stack
    ctx, wf = await published(owner, api, admin, settings)
    if limit is not None:
        async with owner() as s, s.begin():
            await s.execute(text("insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, :n)"),
                            {"t": ctx.tenant_id, "n": limit})  # fmt: skip
    return ctx, [(await admit(api, ctx, wf, key=f"k{i}")).request for i in range(n)]


def started(client: FakeClient) -> list[str]:
    return [workflow_id for _, workflow_id, _ in client.started]


def ids(requests: list[Any]) -> list[str]:
    return [run_workflow_id(str(r.tenant_id), str(r.id)) for r in requests]


@pytest.fixture
async def stack(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings):
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    return owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings


async def test_a_tenants_due_requests_all_start_in_one_cycle_oldest_first(
    stack, dispatch_sessionmaker, api_settings
) -> None:  # fmt: skip
    _, requests = await queued(stack, 5)
    client = FakeClient()
    done = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD, dispatch.Rotation())
    assert done == {"started": 5}
    assert started(client) == ids(requests)


async def test_its_slots_stop_its_rounds(stack, dispatch_sessionmaker, api_settings) -> None:
    owner = stack[0]
    _, requests = await queued(stack, 4, limit=2)
    client = FakeClient()
    done = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD, dispatch.Rotation())
    assert done == {"started": 2, "no_slot": 1}  # its third waits, begun once: its tenant takes no more rounds
    assert started(client) == ids(requests[:2])
    assert [(await state(owner, r.id))["request"][0] for r in requests] == ["started"] * 2 + ["queued"] * 2


async def test_each_round_takes_every_tenant_once(stack, dispatch_sessionmaker, api_settings) -> None:
    _, first = await queued(stack, 3)
    _, second = await queued(stack, 3)
    client = FakeClient()
    done = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD, dispatch.Rotation())
    assert done == {"started": 6}
    assert started(client) == [i for pair in zip(ids(first), ids(second), strict=True) for i in pair]


async def test_a_tenants_held_request_is_passed_by_as_the_pick_passes_it(
    stack, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:  # fmt: skip
    """A request its failures hold (or haven't made due again) is left out of a round as of the cycle's pick."""
    ctx, requests = await queued(stack, 3)
    async with owner_sessionmaker() as s, s.begin():
        held = text(
            "insert into work_failures (tenant_id, kind, item_id, errors, last_error, due_at, held_at) "
            "values (:t, 'dispatch', :i, 7, 'RuntimeError', now(), now())"
        )
        await s.execute(held, {"t": ctx.tenant_id, "i": requests[1].id})
    client = FakeClient()
    done = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD, dispatch.Rotation())
    assert done == {"started": 2}
    assert started(client) == ids([requests[0], requests[2]])


async def test_no_further_round_past_its_time_and_none_past_the_budget(
    stack, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:  # fmt: skip
    """Past `AGAIN_S` the next cycle goes on, nothing deferred; a budget spent defers as before."""
    await queued(stack, 3)
    monkeypatch.setattr(dispatch, "AGAIN_S", 0.0)
    client, rotation = FakeClient(), dispatch.Rotation()
    assert await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD, rotation) == {
        "started": 1
    }
    monkeypatch.setattr(dispatch, "AGAIN_S", 60.0)
    monkeypatch.setattr(budget, "PASS_S", 0.0)
    await queued(stack, 1)  # a second tenant: the budget takes the pick's first only
    assert await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD, rotation) == {
        "started": 1,
        "deferred": 1,
    }


async def test_a_request_dispatch_fails_on_ends_its_tenants_rounds(
    stack, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:  # fmt: skip
    """A bug or an outage on one request: its tenant waits for the next cycle, its count kept (D10)."""
    _, requests = await queued(stack, 3)
    failing = requests[1].id
    begin = dispatch.begin

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        if kwargs["request_id"] == failing:
            raise RuntimeError("an outage")
        return await begin(*args, **kwargs)

    monkeypatch.setattr(dispatch, "begin", flaky)
    client = FakeClient()
    done = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD, dispatch.Rotation())
    assert done == {"started": 1, "error": 1}
    assert started(client) == ids(requests[:1])


def test_a_pass_takes_further_rounds_for_at_most_a_second_by_default() -> None:
    assert dispatch.AGAIN_S == 1.0


async def test_a_tenants_next_due_request_is_the_dispatchers_alone_to_read(owner_sessionmaker) -> None:
    """`dispatch_next(tenants)`: ids and order only, as `dispatch_candidates`."""
    from tests.core.ingress.test_matching_schema import ROLES

    function = "dispatch_next(uuid[])"
    async with owner_sessionmaker() as s:
        allowed = text("select has_function_privilege(:r, :f, 'EXECUTE')")
        assert (await s.execute(allowed, {"r": "dewpoint_dispatch", "f": function})).scalar_one() is True
        for role in ROLES:
            assert (await s.execute(allowed, {"r": role, "f": function})).scalar_one() is False, role
        query = text("select prosecdef, proconfig, proacl::text from pg_proc where oid = cast(:f as regprocedure)")
        definer, config, acl = (await s.execute(query, {"f": function})).one()
        assert (definer, config) == (True, ["search_path=public, pg_temp"])
        assert not any(entry.startswith("=") for entry in acl.strip("{}").split(","))
