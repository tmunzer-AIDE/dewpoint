# SPDX-License-Identifier: Apache-2.0
"""A tenant's queued ingress requests, bounded (the owner's ruling 2 on 2b-4b's M3 checkpoint 2). Matching admits an
event's requests only while the tenant's queued webhook requests and the event's matching bindings stay within its
cap. Past it the event stays pending (`backlog_full`), nothing written, and the tenant's later events are passed by for
the pass, so its order is kept; ingress's pending quota answers senders meanwhile (429). The count is taken under the
tenant's counter row, which a matcher takes `SKIP LOCKED`: two matchers never both admit past it. The cap follows the
deployment's measured starts, headroom and agreed wait once all three are set, a development-only one until then."""

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.dispatcher import matching
from tests.apps.dispatcher.inbound import bind, endpoint, event_state, send
from tests.apps.dispatcher.test_matching import ALARM, dev, ready  # noqa: F401
from tests.apps.test_admission import KEYS, OPEN_GRAPH
from tests.apps.test_workflow_ops import create, publish


async def fanned_out(stack: tuple[Any, ...], inbound: Any, n: int, *others: uuid.UUID) -> None:
    """`n` enabled bindings on the endpoint (and on each of `others`), each to a published workflow of its own."""
    owner, api, settings = stack
    workflows = [inbound.workflow_id]
    for k in range(n - 1):
        workflow = await create(api, inbound.ctx, OPEN_GRAPH, name=f"fan-{k}")
        assert (await publish(api, inbound.ctx, workflow, settings)).version is not None
        workflows.append(workflow)
    for endpoint_id in (inbound.endpoint_id, *others):
        for workflow in workflows:
            await bind(owner, inbound, workflow, endpoint_id=endpoint_id)


async def arrived(ingress: Any, inbound: Any, n: int, *endpoints: uuid.UUID) -> list[uuid.UUID]:
    """`n` events, one a request, each after the one before, to `endpoints` in turn (else the inbound one)."""
    to = endpoints or (inbound.endpoint_id,)
    return [(await send(ingress, inbound, {**ALARM, "id": f"a-{k}"}, endpoint_id=to[k % len(to)]))[0]
            for k in range(n)]  # fmt: skip


async def queued(owner: Any, tenant_id: uuid.UUID) -> int:
    async with owner() as s:
        found = await s.execute(text("select count(*) from run_requests where tenant_id = :t and status = 'queued' "
                                     "and source = 'webhook'"), {"t": tenant_id})  # fmt: skip
        return int(found.scalar_one())


async def test_an_event_past_its_tenants_cap_stays_pending_and_its_later_events_wait_behind_it(
    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, api_sessionmaker, api_settings, monkeypatch  # noqa: F811
) -> None:  # fmt: skip
    monkeypatch.setattr(matching, "DEV_QUEUED", 7)
    await fanned_out((owner_sessionmaker, api_sessionmaker, api_settings), dev, 3)
    ids = await arrived(ingress_sessionmaker, dev, 4)
    done = await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified())
    assert done == {"matched": 2, "backlog_full": 1, "busy_tenant": 1}  # 6 queued: a third event's 3 would pass 7
    assert [(await event_state(owner_sessionmaker, i))["status"] for i in ids] == ["matched"] * 2 + ["pending"] * 2
    assert await queued(owner_sessionmaker, dev.tenant_id) == 6
    async with owner_sessionmaker() as s, s.begin():  # the queue drains: its requests start
        await s.execute(text("update run_requests set status = 'cancelled', reason = 'user_cancelled', "
                             "ended_at = now() where tenant_id = :t"), {"t": dev.tenant_id})  # fmt: skip
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {"matched": 2}
    assert await queued(owner_sessionmaker, dev.tenant_id) == 6


async def test_matchers_at_once_never_admit_past_the_cap(
    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, api_sessionmaker, api_settings, monkeypatch  # noqa: F811
) -> None:  # fmt: skip
    """Four dispatchers' passes at once, each match held a moment once it has its event, the events on two endpoints
    (whose rows don't serialize the matches): the cap counted under the tenant's counter row holds whoever matches."""
    monkeypatch.setattr(matching, "DEV_QUEUED", 10)

    async def held() -> None:
        await asyncio.sleep(0.05)

    monkeypatch.setattr(matching, "_after_event_locked", held)
    second = await endpoint(owner_sessionmaker, dev.tenant_id, dev.user_id)
    await fanned_out((owner_sessionmaker, api_sessionmaker, api_settings), dev, 3, second)
    ids = await arrived(ingress_sessionmaker, dev, 8, dev.endpoint_id, second)
    for _ in range(3):
        await asyncio.gather(*(matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified())
                               for _ in range(4)))  # fmt: skip
        assert await queued(owner_sessionmaker, dev.tenant_id) <= 10
    statuses = [(await event_state(owner_sessionmaker, i))["status"] for i in ids]
    assert statuses == ["matched"] * 3 + ["pending"] * 5  # oldest first, 9 queued: a fourth's 3 would pass 10
    assert await queued(owner_sessionmaker, dev.tenant_id) == 9


def platform(starts: float | None, headroom: float | None, wait_s: int | None) -> Any:
    return SimpleNamespace(ingress_starts_per_s=starts, ingress_headroom=headroom, ingress_queue_wait_s=wait_s)


@pytest.mark.parametrize(
    ("given", "cap"),
    [
        ((None, None, None), "dev"),  # not measured: the development-only cap
        ((8.0, 0.5, None), "dev"),  # no wait agreed: the same
        ((8.0, 0.5, 300), 1_200),  # 4 starts a second, 300 s of them
        ((1.0, 0.1, 10), 20),  # never below an event's most bindings: it must fit, or it never matches
    ],
)
def test_the_cap_follows_the_measured_starts_the_headroom_and_the_agreed_wait(given: Any, cap: Any) -> None:
    assert matching.queue_cap(platform(*given)) == (matching.DEV_QUEUED if cap == "dev" else cap)
