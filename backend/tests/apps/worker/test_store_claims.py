# SPDX-License-Identifier: Apache-2.0
"""The worker's claim store over the database (engine 2b spec §3.1, §3.3): as the worker role, inside the tenant, a
claim written for a run is read back by it and refused to any other run, whatever the cause."""

import uuid
from typing import Any

import pytest

from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.claims import service
from dewpoint.engine import handles
from dewpoint.engine.handles import StoredClaim
from tests.core.claims.test_service import a_tenant
from tests.support.keys import FixtureKeys


async def test_a_claim_is_read_back_by_its_run_and_refused_to_any_other(
    owner_sessionmaker: Any, worker_sessionmaker: Any
) -> None:
    tenant, run, other = await a_tenant(owner_sessionmaker), uuid.uuid4(), uuid.uuid4()
    store = DbRunStore(worker_sessionmaker, FixtureKeys())
    new = service.NewClaim(uuid.uuid4(), {"token": "s3cr3t"}, ("/token",), run, run)
    await store.write(str(tenant), [new], kind="cel", step_id=str(uuid.uuid4()), iteration_key="")
    await store.write(str(tenant), [new], kind="cel", step_id=None, iteration_key=None)  # a retry: the same row
    assert await store.fetch(str(tenant), str(run), str(new.id)) == StoredClaim({"token": "s3cr3t"}, ("/token",))
    for reader, scope in ((other, tenant), (run, await a_tenant(owner_sessionmaker))):
        with pytest.raises(service.ClaimUnavailableError):
            await store.fetch(str(scope), str(reader), str(new.id))


def test_the_engine_names_the_refusal_as_the_store_does() -> None:
    assert handles.CLAIM_UNAVAILABLE == service.CLAIM_UNAVAILABLE


async def test_a_crossing_reads_its_closure_and_grants_it_in_statements_counted_by_thousands(
    owner_sessionmaker, worker_sessionmaker
) -> None:  # fmt: skip
    """The M2 measurement, a crossing as a real one is (the owner's ruling, 2b-4b M3): 1,500 listed claims, every tenth
    nesting one that nests another (three levels), all held by grant. Each claim's closure read was a session of its
    own and three statements, and each grant check two more: about 7 ms a claim. A level of the closure is read a
    thousand claims a statement now, and its grant checked as much: every claim granted, in a few dozen statements."""
    from dewpoint.apps.worker.claims import _granted
    from dewpoint.core.db import tenant_scope
    from dewpoint.engine.handles import ClaimRef
    from tests.core.claims.test_service import statements

    tenant, owner, run, child = await a_tenant(owner_sessionmaker), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    store = DbRunStore(worker_sessionmaker, FixtureKeys())
    deepest = [uuid.uuid4() for _ in range(15)]
    middle = [uuid.uuid4() for _ in range(150)]
    listed = [uuid.uuid4() for _ in range(1_500)]
    made = [service.NewClaim(c, {"v": n}, (), owner, owner) for n, c in enumerate(deepest)]
    made += [service.NewClaim(c, {"v": n, "in": ClaimRef(str(deepest[n // 10])).to_json()} if n % 10 == 0
                              else {"v": n}, (), owner, owner) for n, c in enumerate(middle)]  # fmt: skip
    made += [service.NewClaim(c, {"v": n, "in": ClaimRef(str(middle[n // 10])).to_json()} if n % 10 == 0
                              else {"v": n}, (), owner, owner) for n, c in enumerate(listed)]  # fmt: skip
    await store.write(str(tenant), made, kind="output", step_id=None, iteration_key=None)
    every = [str(c.id) for c in made]
    await store.grant(str(tenant), granted_by=str(owner), to=str(run), claim_ids=every, root_run_id=str(owner))
    value = {"xs": [ClaimRef(str(c)).to_json() for c in listed]}
    with statements(worker_sessionmaker) as seen:
        await _granted(store, str(tenant), str(run), str(child), value, str(owner))
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        granted = [c async for group in service.fetch_groups(s, service.ClaimCipher(FixtureKeys()), tenant,
                                                             run_id=child, claim_ids=[c.id for c in made])
                   for c in group]  # fmt: skip
    assert len(granted) == 1_665
    assert len(seen) <= 40, len(seen)


SITES = {  # a sub-flow's input: rows, each with a sensitive key
    "type": "object",
    "properties": {"sites": {"type": "array", "items": {"type": "object", "properties": {
        "site": {"type": "string"}, "psk": {"type": "string", "x-sensitive": True}}, "additionalProperties": False}}},
    "required": ["sites"],
    "additionalProperties": False,
}  # fmt: skip


async def sites_held_by_grant(
    stack: tuple[Any, ...], n: int, *, withheld: int = 0
) -> tuple[uuid.UUID, str, uuid.UUID, uuid.UUID, dict[str, Any], list[uuid.UUID]]:
    """A child version taking `sites`, and a run holding by grant `n` rows' claim nesting a sensitive claim a row (all
    but the last `withheld` granted): (tenant, the child version, the root, the run, its input, every claim)."""
    from sqlalchemy import text

    from dewpoint.engine.handles import ClaimRef
    from tests.apps.test_admission import published
    from tests.support.graphs import G

    owner, api, admin, worker, settings = stack
    graph = G().node("e", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": SITES}}
    ctx, wf = await published(owner, api, admin, settings, graph)
    async with owner() as s:
        version = (await s.execute(text("select id from workflow_versions where workflow_id = :w"), {"w": wf})).scalar()
    root, run = uuid.uuid4(), uuid.uuid4()
    store = DbRunStore(worker, FixtureKeys())
    keys = [service.NewClaim(uuid.uuid4(), f"psk-{i:05d}-s3cret", ("",), root, root) for i in range(n)]
    rows = service.NewClaim(uuid.uuid4(), [{"site": f"site-{i:05d}", "psk": ClaimRef(str(k.id)).to_json()}
                                           for i, k in enumerate(keys)], (), root, root)  # fmt: skip
    await store.write(str(ctx.tenant_id), [*keys, rows], kind="output", step_id=None, iteration_key=None)
    every = [c.id for c in (*keys, rows)]
    granted = [str(c) for c in every[: len(every) - 1 - withheld]] + [str(rows.id)]
    await store.grant(str(ctx.tenant_id), granted_by=str(root), to=str(run), claim_ids=granted, root_run_id=str(root))
    return ctx.tenant_id, str(version), root, run, {"sites": ClaimRef(str(rows.id)).to_json()}, every


async def crossed(tenant: uuid.UUID, version: str, root: uuid.UUID, run: uuid.UUID, child: uuid.UUID,
                  value: dict[str, Any], store: DbRunStore) -> Any:  # fmt: skip
    """`claims.child_input` as the run's activity calls it."""
    import dataclasses

    from temporalio.testing import ActivityEnvironment

    from dewpoint.apps.worker.claims import child_input
    from dewpoint.engine.runtime.activities import ChildInput
    from dewpoint.engine.runtime.ids import run_workflow_id

    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, workflow_id=run_workflow_id(str(tenant), str(run)))
    return await env.run(child_input, ChildInput(str(child), version, value, str(root)), store)


async def granted_to(worker: Any, tenant: uuid.UUID, child: uuid.UUID) -> int:
    from sqlalchemy import text

    from dewpoint.core.db import tenant_scope

    async with worker() as s, s.begin():
        await tenant_scope(s, tenant)
        return int(
            (await s.execute(text("select count(*) from claim_grants where run_id = :c"), {"c": child})).scalar()
        )


@pytest.mark.parametrize("n", [500, 3_000])
async def test_a_sub_flows_input_reads_its_claims_a_thousand_a_statement_once(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings, n: int
) -> None:  # fmt: skip
    """The owner's ruling on the M3 checkpoint 2: the whole 10,000-claim run's first crossing took 38.5 s of its
    minute. `claims.child_input` resolved its input one claim a session to check it against the child's schema, again
    for each sensitive position it reclassified, then read the closure a third time to grant it. It reads the closure
    once now, a thousand claims a statement (each checked as one read alone is), and grants what it read: its
    statements grow by thousands of claims, not by claim (12,048 statements for 1,501 claims before; 26 for 501, 36
    for 1,501 and 50 for 3,001 after)."""
    import math

    from tests.core.claims.test_service import statements

    stack = (owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings)
    tenant, version, root, run, value, every = await sites_held_by_grant(stack, n)
    store, child = DbRunStore(worker_sessionmaker, FixtureKeys()), uuid.uuid4()
    with statements(worker_sessionmaker) as seen:
        result = await crossed(tenant, version, root, run, child, value, store)
    assert result.reasons == []
    assert list(result.trigger) == ["sites"] and "$claim" in result.trigger["sites"]  # the rows claimed for the child
    assert await granted_to(worker_sessionmaker, tenant, child) == len(every)
    assert len(seen) <= 20 + 10 * math.ceil((n + 1) / 1_000), len(seen)  # the rows' claim and n keys


async def test_a_claim_of_a_sub_flows_input_its_run_may_not_read_refuses_it_granting_nothing(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings
) -> None:  # fmt: skip
    from temporalio.exceptions import ApplicationError

    from dewpoint.engine.handles import CLAIM_UNAVAILABLE

    stack = (owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings)
    tenant, version, root, run, value, _ = await sites_held_by_grant(stack, 20, withheld=1)
    child = uuid.uuid4()
    with pytest.raises(ApplicationError) as refused:
        await crossed(tenant, version, root, run, child, value, DbRunStore(worker_sessionmaker, FixtureKeys()))
    assert (refused.value.type, refused.value.non_retryable) == (CLAIM_UNAVAILABLE, True)
    assert await granted_to(worker_sessionmaker, tenant, child) == 0


async def test_a_sub_flows_input_holds_at_once_only_its_byte_budget_of_the_claims_it_reads(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, worker_sessionmaker, api_settings, monkeypatch
) -> None:  # fmt: skip
    """The fresh M3 review 3's I1 (the owner's ruling 3 on the M3 checkpoint 2 kept the crossing's byte-bounded
    memory): a handle pointing at one item of a collected list of 200 large items. The crossing grants the closure,
    every item, and resolves the one it points at; it never holds the items' values together: their ciphertexts a
    group at a time, and the values kept for resolution within `HELD_BYTES`, the rest read again alone."""
    import tracemalloc

    from sqlalchemy import text

    from dewpoint.apps.worker import claims as worker_claims
    from dewpoint.engine.handles import ClaimRef
    from tests.apps.test_admission import published
    from tests.support.graphs import G

    monkeypatch.setattr(service, "GROUP_BYTES", 256 * 1024)
    monkeypatch.setattr(worker_claims, "HELD_BYTES", 1024 * 1024, raising=False)
    item_schema = {"type": "object", "properties": {"item": {"type": "object", "properties": {
        "pad": {"type": "string"}}, "additionalProperties": False}}, "required": ["item"],
        "additionalProperties": False}  # fmt: skip
    graph = G().node("e", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": item_schema}}
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph)
    async with owner_sessionmaker() as s:
        version = (await s.execute(text("select id from workflow_versions where workflow_id = :w"), {"w": wf})).scalar()
    root, run, child = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    store = DbRunStore(worker_sessionmaker, FixtureKeys())
    items = [service.NewClaim(uuid.uuid4(), {"pad": f"{n:05d}" + "x" * 65_000}, (), root, root) for n in range(200)]
    collected = service.NewClaim(uuid.uuid4(), [ClaimRef(str(i.id)).to_json() for i in items], (), root, root)
    await store.write(str(ctx.tenant_id), [*items, collected], kind="output", step_id=None, iteration_key=None)
    every = [str(c.id) for c in (*items, collected)]
    await store.grant(str(ctx.tenant_id), granted_by=str(root), to=str(run), claim_ids=every, root_run_id=str(root))
    value = {"item": ClaimRef(str(collected.id), "/0").to_json()}
    tracemalloc.start()
    try:
        result = await crossed(ctx.tenant_id, str(version), root, run, child, value, store)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.reasons == []
    assert await granted_to(worker_sessionmaker, ctx.tenant_id, child) == 201  # the closure, every item
    assert peak < 6 * 1024 * 1024, peak  # the 200 items are 13 MB: never together
