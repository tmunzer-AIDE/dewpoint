# SPDX-License-Identifier: Apache-2.0
"""The late-create/stale-unpause race, on Temporal (the owner's ruling on the 2b-4a M4 checkpoint). Under one schedule
id it lands: a schedule deleted and recreated counts its conflict token from 1 again, so an unpause computed before the
deletion unpauses a create that landed after it (`test_temporal_erasure_contract.py`). With an incarnation per create,
recorded before the call, it can't: the late create lands under an id no describe ever showed, so the stale unpause
targets another id; the late one stays paused, and the erasure, which covers every incarnation, finds it at its final
check and deletes it. That fixes one premise of the firing bound, not the bound itself (ticks still have no execution
timeout), so completion stays held."""

from typing import Any

import pytest
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import schedule_sync
from dewpoint.apps.erasure import bound, process, temporal
from dewpoint.core.models.erasure import Stage
from tests.apps.dispatcher.test_schedule_sync import Leading
from tests.apps.erasure.support import erasing, populated
from tests.apps.erasure.test_stages import record, until
from tests.apps.test_runs import rpc
from tests.core.retention.support import sql

pytestmark = pytest.mark.usefixtures("development_deployment")


async def test_a_late_create_and_a_stale_unpause_never_meet_and_the_erasure_deletes_every_incarnation(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, dispatch_sessionmaker,
    monkeypatch,
) -> None:  # fmt: skip
    data = await populated(owner_sessionmaker, ingress_sessionmaker)
    client, tenant, schedule_id = server.client, data["t"], data["schedule"]
    creates: list[tuple[str, Any]] = []
    unpauses: list[tuple[str, Any, bytes]] = []
    real_create, real_update = schedule_sync._create, schedule_sync._update

    async def lost_create(_: Any, temporal_id: str, schedule: Any) -> bool:
        creates.append((temporal_id, schedule))
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    async def lost_update(_: Any, temporal_id: str, schedule: Any, token: bytes) -> None:
        unpauses.append((temporal_id, schedule, token))
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    async def synced() -> None:
        with pytest.raises(RPCError):
            await schedule_sync.sync_one(dispatch_sessionmaker, client, Leading(), tenant, schedule_id)

    monkeypatch.setattr(schedule_sync, "_create", lost_create)
    await synced()  # a create, in flight: it will land late
    monkeypatch.setattr(schedule_sync, "_create", real_create)
    monkeypatch.setattr(schedule_sync, "_update", lost_update)
    await synced()  # the next incarnation created (paused); its unpause, in flight: it will land late
    monkeypatch.setattr(schedule_sync, "_update", real_update)
    [(late, its_schedule)] = creates
    [(target, wanted, token)] = unpauses
    assert late != target and token == (1).to_bytes(8, "big")  # the token a recreation would have too

    await erasing(api_sessionmaker, tenant)
    assert await until(retention_sessionmaker, client, tenant, Stage.BOUND) == Stage.BOUND
    assert await temporal.schedule(client, target) is None  # paused, inventoried, deleted
    assert await real_create(client, late, its_schedule)  # the late create lands, after the deletion
    with pytest.raises(RPCError) as stale:  # the stale unpause names the id it described: deleted
        await real_update(client, target, wanted, token)
    assert stale.value.status == RPCStatusCode.NOT_FOUND
    landed = await temporal.schedule(client, late)
    assert landed is not None and landed.paused and landed.executions == []  # it fires nothing

    monkeypatch.setattr(bound, "FIRING_BOUND", "proven for the test")  # to run the final check
    await sql(owner_sessionmaker, "insert into namespace_boundaries (name) values ('test boundary')")
    await process.advance(retention_sessionmaker, client, tenant)
    await sql(owner_sessionmaker, "update tenant_erasures set check_after = now() - interval '1 second' "
              "where tenant_id = :t", t=tenant)  # fmt: skip
    assert await until(retention_sessionmaker, client, tenant, Stage.BOUND) == Stage.BOUND
    assert (await record(owner_sessionmaker, tenant)).incidents == 1  # found at the final check, as every incarnation
    assert await temporal.schedule(client, late) is None
