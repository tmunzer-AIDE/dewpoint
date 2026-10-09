# SPDX-License-Identifier: Apache-2.0
"""An endpoint's and a tenant's event rates, derived (the owner's ruling 2 on 2b-4b's M3 checkpoint 2). Once the
deployment's ingress capacity is set, a tenant's events come at most at the headroom's share of its measured starts,
and an endpoint's at that divided by its enabled bindings (an event becomes a request for each); before, the rates as
configured, development-only. A rate configured lower stays; bursts are as configured."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from tests.core.ingress.support import digest, endpoint, key, record

pytestmark = pytest.mark.usefixtures("development_deployment")


async def capacity(owner: Any, starts: float | None, headroom: float | None) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("update platform_settings set ingress_starts_per_s = :s, ingress_headroom = :h"),
                        {"s": starts, "h": headroom})  # fmt: skip


async def bound(owner: Any, tenant: uuid.UUID, endpoint_id: uuid.UUID, n: int, *, enabled: bool = True) -> None:
    """`n` bindings of the endpoint, each to a workflow of its own."""
    async with owner() as s, s.begin():
        user = (await s.execute(text("select created_by from webhook_endpoints where id = :e"),
                                {"e": endpoint_id})).scalar_one()  # fmt: skip
        for _ in range(n):
            workflow = uuid.uuid4()
            await s.execute(
                text("insert into workflows (id, tenant_id, name, enabled, draft) values (:w, :t, :n, true, '{}')"),
                {"w": workflow, "t": tenant, "n": workflow.hex},
            )
            await s.execute(text("insert into trigger_bindings (id, tenant_id, endpoint_id, workflow_id, filter, "
                                 "enabled, created_by) values (:b, :t, :e, :w, '[]', :on, :u)"),
                            {"b": uuid.uuid4(), "t": tenant, "e": endpoint_id, "w": workflow, "on": enabled,
                             "u": user})  # fmt: skip


def events(n: int, at: int = 0) -> list[tuple[bytes | None, bytes | None, bytes]]:
    return [(key(at + i), digest(at + i), b"event") for i in range(n)]


async def drained(owner: Any, *, endpoint_id: uuid.UUID | None = None, tenant: uuid.UUID | None = None) -> None:
    """A bucket spent just now, so an attempt waits its events at the rate: buckets refill while a test sets up."""
    async with owner() as s, s.begin():
        if endpoint_id is not None:
            await s.execute(text("update webhook_endpoints set event_tokens = 0, refilled_at = clock_timestamp() "
                                 "where id = :e"), {"e": endpoint_id})  # fmt: skip
        if tenant is not None:
            await s.execute(text("update tenant_event_counters set event_tokens = 0, "
                                 "refilled_at = clock_timestamp() where tenant_id = :t"), {"t": tenant})  # fmt: skip


async def limited(ingress: Any, endpoint_id: uuid.UUID, n: int, at: int) -> int:
    """How long an attempt of `n` events is told to wait."""
    outcome = await record(ingress, endpoint_id, events(n, at))
    assert outcome["outcome"] == "rate_limited", outcome
    return int(outcome["retry_after"])


async def test_an_endpoints_rate_is_its_share_of_the_measured_starts_by_its_enabled_bindings(
    owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    tenant, endpoint_id = await endpoint(owner_sessionmaker)
    await bound(owner_sessionmaker, tenant, endpoint_id, 4)
    await bound(owner_sessionmaker, tenant, endpoint_id, 1, enabled=False)
    await drained(owner_sessionmaker, endpoint_id=endpoint_id)
    assert await limited(ingress_sessionmaker, endpoint_id, 10, 0) == 1  # 10 events at its 10 a second
    await capacity(owner_sessionmaker, 8.0, 0.5)  # 4 starts a second: an event a second for 4 enabled bindings
    await drained(owner_sessionmaker, endpoint_id=endpoint_id)
    assert 8 <= await limited(ingress_sessionmaker, endpoint_id, 10, 10) <= 10


async def test_a_tenants_rate_is_the_share_of_the_measured_starts_and_a_lower_configured_rate_stays(
    owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    tenant, endpoint_id = await endpoint(owner_sessionmaker, event_tokens=1_000, event_per_s=1_000)
    await bound(owner_sessionmaker, tenant, endpoint_id, 1)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into tenant_event_counters (tenant_id) values (:t)"), {"t": tenant})
    await drained(owner_sessionmaker, tenant=tenant)
    assert await limited(ingress_sessionmaker, endpoint_id, 10, 0) == 1  # at its configured 10 a second
    await capacity(owner_sessionmaker, 8.0, 0.5)  # 4 a second for the tenant: 10 events wait 2.5 s
    await drained(owner_sessionmaker, tenant=tenant)
    assert 2 <= await limited(ingress_sessionmaker, endpoint_id, 10, 10) <= 3
    await capacity(owner_sessionmaker, 800.0, 0.5)  # 400 a second: its configured 10 stays
    await drained(owner_sessionmaker, tenant=tenant)
    assert await limited(ingress_sessionmaker, endpoint_id, 10, 20) == 1


async def test_a_tenants_rate_is_divided_by_its_largest_fan_out_whichever_endpoint_its_events_reach(
    owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    """The fresh M3 review 3's I2: an event becomes at most as many requests as the tenant's largest fan-out, so its
    events come at most at the budget divided by it, and its requests at most at the budget, however they spread
    over its endpoints."""
    import hashlib

    tenant, wide = await endpoint(owner_sessionmaker)
    await bound(owner_sessionmaker, tenant, wide, 4)
    narrow = uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        user = (await s.execute(text("select created_by from webhook_endpoints where id = :e"),
                                {"e": wide})).scalar_one()  # fmt: skip
        await s.execute(text("insert into webhook_endpoints (id, tenant_id, name, created_by, auth_kind, "
                             "bearer_digest, dedupe_key, event_tokens, event_per_s) values (:e, :t, 'narrow', :u, "
                             "'bearer', :d, 'sealed-dedupe-key', 1000, 1000)"),
                        {"e": narrow, "t": tenant, "u": user, "d": hashlib.sha256(b"token").digest()})  # fmt: skip
        await s.execute(text("insert into tenant_event_counters (tenant_id) values (:t)"), {"t": tenant})
    await bound(owner_sessionmaker, tenant, narrow, 1)
    await capacity(owner_sessionmaker, 8.0, 0.5)  # 4 starts a second; 4 bindings at most: an event a second
    await drained(owner_sessionmaker, tenant=tenant)
    assert 8 <= await limited(ingress_sessionmaker, narrow, 10, 0) <= 10  # at 4 a second, 3
