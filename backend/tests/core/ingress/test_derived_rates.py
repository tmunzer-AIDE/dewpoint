# SPDX-License-Identifier: Apache-2.0
"""An endpoint's event rate, derived (the owner's rulings on 2b-4b's M3 checkpoints 2 and 4). Once the deployment's
ingress capacity is set, an endpoint's events come at most at the headroom's share of its measured starts divided by its
enabled bindings (an event becomes a request for each), to smooth a sender; before, as configured, development-only. A
rate configured lower stays; bursts are as configured. A tenant's rate stays as configured: the deployment's budget, not
a rate, bounds its work outstanding (tests/apps/dispatcher/test_ingress_budget.py)."""

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


async def test_a_tenants_rate_stays_as_configured_once_the_capacity_is_set(
    owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    """The checkpoint-3 derivation (the budget over the tenant's widest fan-out) went with the per-tenant queue cap:
    the deployment's budget bounds what a tenant's events become."""
    tenant, endpoint_id = await endpoint(owner_sessionmaker, event_tokens=1_000, event_per_s=1_000)
    await bound(owner_sessionmaker, tenant, endpoint_id, 4)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into tenant_event_counters (tenant_id) values (:t)"), {"t": tenant})
    await capacity(owner_sessionmaker, 8.0, 0.5)  # 4 starts a second, 4 bindings: once, an event a second
    await drained(owner_sessionmaker, tenant=tenant)
    assert await limited(ingress_sessionmaker, endpoint_id, 10, 0) == 1  # at its configured 10 a second
