# SPDX-License-Identifier: Apache-2.0
"""Matching (engine 2b spec §8.3; "Functions and lock order" in the 2b-3b outline): every dispatcher, only while the
gate is on, one transaction per event. It takes the gate's and the tenant's lifecycle locks shared and rechecks the
gate and the tenant; locks the event's endpoint row, the tenant's counter row, then the event row with SKIP LOCKED,
rechecking it's still pending; opens it; admits one request per matching binding (source `webhook`, key
`evt:<event id>:<workflow id>`, the event as the trigger), in workflow-id order; records `matched` with its request
count, or `unmatched`; and releases the pending counters. A recheck that fails changes nothing."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import admission
from dewpoint.apps.dispatcher import matching
from dewpoint.core.platform.service import PRODUCTION, record_environment
from tests.apps.dispatcher.inbound import (
    bind,
    counters,
    event_state,
    inbound,
    lock_waiters,
    requests_of,
    send,
    stored,
)
from tests.apps.test_admission import KEYS
from tests.core.ingress.support import RECORD

ALARM = {"id": "a-1", "type": "ap_down", "site": "s-1", "count": 2}


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    return await inbound(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)


@pytest.fixture
async def dev(development_deployment, ready):  # type: ignore[no-untyped-def]
    return ready


async def matched(dispatch: Any, inbound: Any, event_id: uuid.UUID, verified: Any = None) -> str:
    return await matching.match_event(
        dispatch,
        KEYS,
        verified if verified is not None else matching.Verified(),
        tenant_id=inbound.tenant_id,
        event_id=event_id,
        endpoint_id=inbound.endpoint_id,
    )


async def other_workflow(owner: Any, inbound: Any) -> uuid.UUID:
    workflow_id = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into workflows (id, tenant_id, name, enabled, draft) values (:w, :t, :n, true, '{}')"),
            {"w": workflow_id, "t": inbound.tenant_id, "n": f"w-{workflow_id.hex[:8]}"},
        )
    return workflow_id


async def test_an_event_admits_one_request_per_matching_binding_in_workflow_order(
    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, api_sessionmaker, admin_sessionmaker,
    api_settings, monkeypatch,
) -> None:  # fmt: skip
    from tests.apps.test_admission import OPEN_GRAPH
    from tests.apps.test_workflow_ops import create, publish

    second = await create(api_sessionmaker, dev.ctx, OPEN_GRAPH, name="W2")
    assert (await publish(api_sessionmaker, dev.ctx, second, api_settings)).version is not None
    await bind(owner_sessionmaker, dev)
    await bind(owner_sessionmaker, dev, second)
    order: list[uuid.UUID] = []
    admit = admission.admit_request

    async def recorded(*args: Any, **kwargs: Any) -> Any:
        order.append(kwargs["workflow_id"])
        return await admit(*args, **kwargs)

    monkeypatch.setattr(admission, "admit_request", recorded)
    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
    assert await matched(dispatch_sessionmaker, dev, event_id) == "matched"
    assert order == sorted([dev.workflow_id, second])
    found = await requests_of(owner_sessionmaker, event_id)
    assert [(r["idempotency_key"], r["source"], r["mode"], r["status"]) for r in found] == sorted(
        (f"evt:{event_id}:{w}", "webhook", "live", "queued") for w in (dev.workflow_id, second)
    )
    state = await event_state(owner_sessionmaker, event_id)
    assert (state["status"], state["request_count"], state["attempts"]) == ("matched", 2, 0)
    assert state["ended_at"] is not None
    assert await counters(owner_sessionmaker, dev) == ((0, 0), (0, 0))


async def test_a_filter_selects_by_typed_equality_and_no_match_is_unmatched(
    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:
    await bind(owner_sessionmaker, dev, filter=[{"pointer": "/type", "value": "ap_down"}, {"pointer": "/count",
                                                                                         "value": 2}])  # fmt: skip
    hit, typed, miss = await send(ingress_sessionmaker, dev, ALARM, ALARM | {"count": "2"}, ALARM | {"type": "ap_up"})
    assert await matched(dispatch_sessionmaker, dev, hit) == "matched"
    for event_id in (typed, miss):  # "2" isn't 2
        assert await matched(dispatch_sessionmaker, dev, event_id) == "unmatched"
        state = await event_state(owner_sessionmaker, event_id)
        assert (state["status"], state["request_count"]) == ("unmatched", 0)
        assert await requests_of(owner_sessionmaker, event_id) == []
    assert await counters(owner_sessionmaker, dev) == ((0, 0), (0, 0))


async def test_without_an_enabled_binding_an_event_is_unmatched(
    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:
    await bind(owner_sessionmaker, dev, enabled=False)
    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
    assert await matched(dispatch_sessionmaker, dev, event_id) == "unmatched"


async def test_a_refused_admission_is_a_request_too(dev, owner_sessionmaker, ingress_sessionmaker,
                                                   dispatch_sessionmaker) -> None:  # fmt: skip
    await bind(owner_sessionmaker, dev)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update workflows set enabled = false where id = :w"), {"w": dev.workflow_id})
    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
    assert await matched(dispatch_sessionmaker, dev, event_id) == "matched"
    [request] = await requests_of(owner_sessionmaker, event_id)
    assert (request["status"], request["reason"]) == ("refused", admission.WORKFLOW_DISABLED)
    assert (await event_state(owner_sessionmaker, event_id))["request_count"] == 1


async def test_with_the_gate_off_nothing_is_matched(ready, owner_sessionmaker, dispatch_sessionmaker) -> None:
    async with owner_sessionmaker() as s, s.begin():  # a production deployment, its runs off by default (the gate)
        await record_environment(s, environment=PRODUCTION, namespace="default")
    await bind(owner_sessionmaker, ready)
    event_id = await stored(owner_sessionmaker, ready, ALARM)
    assert await matched(dispatch_sessionmaker, ready, event_id) == "gate_off"
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {"gate_off": 1}
    state = await event_state(owner_sessionmaker, event_id)
    assert (state["status"], state["attempts"], state["next_attempt_at"]) == ("pending", 0, None)
    assert await requests_of(owner_sessionmaker, event_id) == []


async def test_an_erasing_tenants_events_wait(dev, owner_sessionmaker, ingress_sessionmaker,
                                              dispatch_sessionmaker) -> None:  # fmt: skip
    await bind(owner_sessionmaker, dev)
    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": dev.tenant_id})
    assert await matched(dispatch_sessionmaker, dev, event_id) == "tenant_erasing"
    assert (await event_state(owner_sessionmaker, event_id))["status"] == "pending"


async def test_more_bindings_than_the_cap_wait_with_an_alert_and_admit_nothing(
    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:
    for _ in range(matching.MAX_BINDINGS + 1):
        await bind(owner_sessionmaker, dev, await other_workflow(owner_sessionmaker, dev))
    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
    assert await matched(dispatch_sessionmaker, dev, event_id) == "fan_out_exceeded"
    state = await event_state(owner_sessionmaker, event_id)
    assert (state["status"], state["attempts"]) == ("pending", 0)
    assert state["next_attempt_at"] is not None  # it backs off, untouched otherwise
    assert await requests_of(owner_sessionmaker, event_id) == []


async def test_a_cycle_matches_the_due_events(dev, owner_sessionmaker, ingress_sessionmaker,
                                              dispatch_sessionmaker) -> None:  # fmt: skip
    await bind(owner_sessionmaker, dev, filter=[{"pointer": "/type", "value": "ap_down"}])
    await send(ingress_sessionmaker, dev, ALARM, ALARM | {"type": "x"}, ALARM | {"id": "a-2"})
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {"matched": 2,
                                                                                            "unmatched": 1}  # fmt: skip
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {}


# Races (the owner's M3 check), each in both orders where order is a question.


_RELEASES: list[asyncio.Event] = []


@pytest.fixture(autouse=True)
async def _released() -> Any:
    """A race test that fails while a match is held releases it before the teardown's truncate, which would otherwise
    wait for that match's locks for ever: a regression fails the test, never hangs the suite."""
    yield
    while _RELEASES:
        _RELEASES.pop().set()
    await asyncio.sleep(0)


async def _held(monkeypatch: Any) -> tuple[asyncio.Event, asyncio.Event]:
    """A matcher that, holding its event's row, waits until released (at the latest when the test ends)."""
    reached, release = asyncio.Event(), asyncio.Event()
    _RELEASES.append(release)

    async def hold() -> None:
        reached.set()
        await release.wait()

    monkeypatch.setattr(matching, "_after_event_locked", hold)
    return reached, release


async def _waiting(owner: Any, n: int = 1) -> None:
    for _ in range(300):
        if await lock_waiters(owner) >= n:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("nothing waited for a lock")


async def test_two_dispatchers_match_an_event_once(dev, owner_sessionmaker, ingress_sessionmaker,
                                                   dispatch_sessionmaker, monkeypatch) -> None:  # fmt: skip
    await bind(owner_sessionmaker, dev)
    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
    reached, release = await _held(monkeypatch)
    first = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
    await reached.wait()
    monkeypatch.setattr(matching, "_after_event_locked", matching_noop)
    second = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
    await _waiting(owner_sessionmaker)  # on the endpoint's row
    release.set()
    assert sorted([await first, await second]) == ["matched", "skipped"]
    assert len(await requests_of(owner_sessionmaker, event_id)) == 1


async def matching_noop() -> None:
    return None


async def test_two_events_of_one_endpoint_are_matched_one_after_the_other(
    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    await bind(owner_sessionmaker, dev)
    one, two = await send(ingress_sessionmaker, dev, ALARM, ALARM | {"id": "a-2"})
    reached, release = await _held(monkeypatch)
    first = asyncio.create_task(matched(dispatch_sessionmaker, dev, one))
    await reached.wait()
    monkeypatch.setattr(matching, "_after_event_locked", matching_noop)
    second = asyncio.create_task(matched(dispatch_sessionmaker, dev, two))
    await _waiting(owner_sessionmaker)
    release.set()
    assert [await first, await second] == ["matched", "matched"]
    assert await counters(owner_sessionmaker, dev) == ((0, 0), (0, 0))


async def test_a_duplicate_recorded_while_its_event_is_matched_is_acknowledged_after(
    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The matcher first: ingress's duplicate waits for the endpoint's row, then finds the event, matched."""
    await bind(owner_sessionmaker, dev)
    key = b"k" * 32
    [event_id] = await send(ingress_sessionmaker, dev, ALARM, dedupe=[key])
    reached, release = await _held(monkeypatch)
    matcher = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
    await reached.wait()
    duplicate = asyncio.create_task(send_raw(ingress_sessionmaker, dev, ALARM, key))
    await _waiting(owner_sessionmaker)
    release.set()
    assert await matcher == "matched"
    assert await duplicate == {"outcome": "recorded", "accepted": 0, "duplicates": 1}
    assert len(await requests_of(owner_sessionmaker, event_id)) == 1
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from inbound_events"))).scalar_one() == 1


async def test_a_duplicate_recorded_first_holds_the_matcher_until_it_commits(
    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:
    """Ingress first: the matcher waits for the endpoint's row, then matches the one event once."""
    await bind(owner_sessionmaker, dev)
    key = b"k" * 32
    [event_id] = await send(ingress_sessionmaker, dev, ALARM, dedupe=[key])
    async with ingress_sessionmaker() as s, s.begin():
        outcome = await s.execute(RECORD, _params(dev, ALARM, key))
        assert dict(outcome.scalar_one())["duplicates"] == 1
        matcher = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
        await _waiting(owner_sessionmaker)
    assert await matcher == "matched"
    assert len(await requests_of(owner_sessionmaker, event_id)) == 1


async def test_a_tenant_marked_erasing_first_is_never_matched(dev, owner_sessionmaker, ingress_sessionmaker,
                                                              dispatch_sessionmaker) -> None:  # fmt: skip
    """2b-4's erasure takes the tenant's lifecycle lock exclusively: the matcher waits for it, then sees `erasing`."""
    await bind(owner_sessionmaker, dev)
    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                        {"k": f"dewpoint:tenant:{dev.tenant_id}"})  # fmt: skip
        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": dev.tenant_id})
        matcher = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
        await _waiting(owner_sessionmaker)
    assert await matcher == "tenant_erasing"
    assert (await event_state(owner_sessionmaker, event_id))["status"] == "pending"


async def test_an_erasure_waits_for_a_match_in_flight(dev, owner_sessionmaker, ingress_sessionmaker,
                                                      dispatch_sessionmaker, monkeypatch) -> None:  # fmt: skip
    await bind(owner_sessionmaker, dev)
    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
    reached, release = await _held(monkeypatch)
    matcher = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
    await reached.wait()

    async def erase() -> None:
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                            {"k": f"dewpoint:tenant:{dev.tenant_id}"})  # fmt: skip
            await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": dev.tenant_id})

    erasure = asyncio.create_task(erase())
    await _waiting(owner_sessionmaker)
    assert not erasure.done()
    release.set()
    assert await matcher == "matched"
    await erasure


async def send_raw(ingress: Any, inbound: Any, payload: object, key: bytes) -> dict[str, Any]:
    async with ingress() as s, s.begin():
        return dict((await s.execute(RECORD, _params(inbound, payload, key))).scalar_one())


def _params(inbound: Any, payload: object, key: bytes) -> dict[str, Any]:
    import hashlib

    from dewpoint.core.ingress.identity import canonical
    from tests.apps.dispatcher.inbound import sealed

    event_id = uuid.uuid4()
    return {"e": inbound.endpoint_id, "refusal": None, "read": 0, "ids": [event_id],
            "sealed": [sealed(inbound, event_id, payload)], "versions": [1], "dedupe": [key],
            "digests": [hashlib.sha256(canonical(payload)).digest()]}  # fmt: skip


async def _cancel(api: Any, inbound: Any, event_id: uuid.UUID) -> str:
    from dewpoint.apps import webhooks
    from dewpoint.core.db import tenant_scope

    try:
        async with api() as s, s.begin():
            await tenant_scope(s, inbound.tenant_id)
            event = await webhooks.cancel_event(s, tenant_id=inbound.tenant_id, event_id=event_id,
                                                actor_id=inbound.user_id)  # fmt: skip
            return event.status
    except webhooks.WebhookRefusedError as e:
        return str(e)


async def test_a_cancel_waits_for_a_match_in_flight_and_finds_it_matched(
    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, api_sessionmaker, monkeypatch
) -> None:
    await bind(owner_sessionmaker, dev)
    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
    reached, release = await _held(monkeypatch)
    matcher = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
    await reached.wait()
    cancel = asyncio.create_task(_cancel(api_sessionmaker, dev, event_id))
    await _waiting(owner_sessionmaker)  # on the endpoint's row
    release.set()
    assert (await matcher, await cancel) == ("matched", "not_cancellable")
    assert await counters(owner_sessionmaker, dev) == ((0, 0), (0, 0))


async def test_a_match_waits_for_a_cancel_and_passes_the_cancelled_event_by(
    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, api_sessionmaker
) -> None:
    from dewpoint.apps import webhooks
    from dewpoint.core.db import tenant_scope

    await bind(owner_sessionmaker, dev)
    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, dev.tenant_id)
        await webhooks.cancel_event(s, tenant_id=dev.tenant_id, event_id=event_id, actor_id=dev.user_id)
        matcher = asyncio.create_task(matched(dispatch_sessionmaker, dev, event_id))
        await _waiting(owner_sessionmaker)
    assert await matcher == "skipped"
    assert await requests_of(owner_sessionmaker, event_id) == []
    assert await counters(owner_sessionmaker, dev) == ((0, 0), (0, 0))
