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
        granted = await service.fetch_many(s, service.ClaimCipher(FixtureKeys()), tenant, run_id=child,
                                           claim_ids=[c.id for c in made])  # fmt: skip
    assert len(granted) == 1_665
    assert len(seen) <= 40, len(seen)
