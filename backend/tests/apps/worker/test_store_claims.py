# SPDX-License-Identifier: Apache-2.0
"""The worker's claim store over the database (engine 2b spec §3.1, §3.3): as the worker role, inside the tenant, a
claim written for a run is read back by it and refused to any other run, whatever the cause."""

import uuid
from typing import Any

import pytest

from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.claims import service
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.engine import handles
from dewpoint.engine.handles import StoredClaim
from tests.core.claims.test_service import a_tenant
from tests.support.keys import FixtureKeys


async def test_a_claim_is_read_back_by_its_run_and_refused_to_any_other(
    owner_sessionmaker: Any, worker_sessionmaker: Any
) -> None:
    tenant, run, other = await a_tenant(owner_sessionmaker), uuid.uuid4(), uuid.uuid4()
    store = DbRunStore(worker_sessionmaker, ClaimCipher(FixtureKeys()))
    new = service.NewClaim(uuid.uuid4(), {"token": "s3cr3t"}, ("/token",), run, run)
    await store.write(str(tenant), [new], kind="cel", step_id=str(uuid.uuid4()), iteration_key="")
    await store.write(str(tenant), [new], kind="cel", step_id=None, iteration_key=None)  # a retry: the same row
    assert await store.fetch(str(tenant), str(run), str(new.id)) == StoredClaim({"token": "s3cr3t"}, ("/token",))
    for reader, scope in ((other, tenant), (run, await a_tenant(owner_sessionmaker))):
        with pytest.raises(service.ClaimUnavailableError):
            await store.fetch(str(scope), str(reader), str(new.id))


def test_the_engine_names_the_refusal_as_the_store_does() -> None:
    assert handles.CLAIM_UNAVAILABLE == service.CLAIM_UNAVAILABLE
