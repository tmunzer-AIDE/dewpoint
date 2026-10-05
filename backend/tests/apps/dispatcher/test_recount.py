# SPDX-License-Identifier: Apache-2.0
"""The recount (engine 2b spec §8.3; "Retained storage" and "Functions and lock order" in the 2b-3b outline): the
leader, per tenant, at most every 10 minutes, takes the tenant's lifecycle lock shared, its endpoint rows in id order
and its counter row **first**, then counts the events and corrects every pending and retained counter that drifted, in
that transaction, so no insert or match in flight is overwritten by a stale total."""

import asyncio
from typing import Any

import pytest
import structlog
from sqlalchemy import text

from dewpoint.apps.dispatcher import matching, recount
from tests.apps.dispatcher.inbound import bind, inbound, lock_waiters, send
from tests.apps.test_admission import KEYS
from tests.core.ingress.support import RECORD

pytestmark = pytest.mark.usefixtures("development_deployment")
ALARM = {"type": "ap_down"}
COUNTERS = "pending_events, pending_bytes, retained_events, retained_bytes"


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    found = await inbound(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
    await bind(owner_sessionmaker, found)
    return found


async def counted(owner: Any, inbound: Any) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """(the endpoint's counters, the tenant's), as stored."""
    async with owner() as s:
        e = (await s.execute(text(f"select {COUNTERS} from webhook_endpoints where id = :e"),  # noqa: S608
                             {"e": inbound.endpoint_id})).one()  # fmt: skip
        t = (await s.execute(text(f"select {COUNTERS} from tenant_event_counters where tenant_id = :t"),  # noqa: S608
                             {"t": inbound.tenant_id})).one()  # fmt: skip
    return tuple(e), tuple(t)


async def truth(owner: Any, inbound: Any) -> tuple[int, ...]:
    """The counters the events themselves say."""
    async with owner() as s:
        row = await s.execute(
            text("select count(*) filter (where status = 'pending'), coalesce(sum(size_bytes) filter (where status = "
                 "'pending'), 0), count(*), coalesce(sum(size_bytes), 0) from inbound_events where endpoint_id = :e"),
            {"e": inbound.endpoint_id},
        )  # fmt: skip
        return tuple(int(v) for v in row.one())


async def drifted(owner: Any, inbound: Any) -> None:
    async with owner() as s, s.begin():
        for table, where in (("webhook_endpoints", "id = :e"), ("tenant_event_counters", "tenant_id = :t")):
            await s.execute(
                text(
                    f"update {table} set pending_events = 99, pending_bytes = 7, retained_events = 0, "  # noqa: S608
                    f"retained_bytes = 1 where {where}"
                ),
                {"e": inbound.endpoint_id, "t": inbound.tenant_id},
            )


async def test_drifted_counters_are_corrected_and_the_tenant_isnt_recounted_again_soon(
    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:
    one, _ = await send(ingress_sessionmaker, ready, ALARM, ALARM | {"n": 2})
    assert await matching.match_event(dispatch_sessionmaker, KEYS, matching.Verified(), tenant_id=ready.tenant_id,
                                      event_id=one, endpoint_id=ready.endpoint_id) == "matched"  # fmt: skip
    right = await truth(owner_sessionmaker, ready)
    await drifted(owner_sessionmaker, ready)
    with structlog.testing.capture_logs() as logs:
        assert await recount.recount_once(dispatch_sessionmaker) == {"recounted": 1, "drifted": 2}
    assert await counted(owner_sessionmaker, ready) == (right, right)
    assert {e["event"] for e in logs} == {"event_counters_drifted"}
    assert await recount.recount_once(dispatch_sessionmaker) == {}  # recounted within the last 10 minutes


async def test_counters_that_agree_are_left_alone(ready, owner_sessionmaker, ingress_sessionmaker,
                                                  dispatch_sessionmaker) -> None:  # fmt: skip
    await send(ingress_sessionmaker, ready, ALARM)
    before = await counted(owner_sessionmaker, ready)
    assert await recount.recount_once(dispatch_sessionmaker) == {"recounted": 1, "drifted": 0}
    assert await counted(owner_sessionmaker, ready) == before


_RELEASES: list[asyncio.Event] = []


@pytest.fixture(autouse=True)
async def _released() -> Any:
    """A race test that fails while a recount or a match is held releases it before the teardown's truncate, which
    would otherwise wait for its locks for ever: a regression fails the test, never hangs the suite."""
    yield
    while _RELEASES:
        _RELEASES.pop().set()
    await asyncio.sleep(0)


async def _held(monkeypatch: Any, module: Any, hook: str) -> tuple[asyncio.Event, asyncio.Event]:
    """A recount or a match that, holding its rows, waits until released (at the latest when the test ends)."""
    reached, release = asyncio.Event(), asyncio.Event()
    _RELEASES.append(release)

    async def hold() -> None:
        reached.set()
        await release.wait()

    monkeypatch.setattr(module, hook, hold)
    return reached, release


async def _waiting(owner: Any) -> None:
    for _ in range(300):
        if await lock_waiters(owner):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("nothing waited for a lock")


async def _insert(ingress: Any, inbound: Any) -> Any:
    from tests.apps.dispatcher.test_matching import _params

    async with ingress() as s, s.begin():
        return dict((await s.execute(RECORD, _params(inbound, ALARM | {"late": True}, b"z" * 32))).scalar_one())


async def test_an_insert_waits_for_a_recount_and_is_counted_after_it(
    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    await send(ingress_sessionmaker, ready, ALARM)
    await drifted(owner_sessionmaker, ready)
    reached, release = await _held(monkeypatch, recount, "_after_recount_locked")
    counting = asyncio.create_task(recount.recount_once(dispatch_sessionmaker))
    await reached.wait()
    inserting = asyncio.create_task(_insert(ingress_sessionmaker, ready))
    await _waiting(owner_sessionmaker)  # on the endpoint's row
    release.set()
    await counting
    assert (await inserting)["accepted"] == 1
    right = await truth(owner_sessionmaker, ready)
    assert right[0] == 2 and await counted(owner_sessionmaker, ready) == (right, right)


async def test_a_recount_waits_for_an_insert_and_counts_it(ready, owner_sessionmaker, ingress_sessionmaker,
                                                           dispatch_sessionmaker) -> None:  # fmt: skip
    from tests.apps.dispatcher.test_matching import _params

    await send(ingress_sessionmaker, ready, ALARM)
    await drifted(owner_sessionmaker, ready)
    async with ingress_sessionmaker() as s, s.begin():
        await s.execute(RECORD, _params(ready, ALARM | {"late": True}, b"z" * 32))
        counting = asyncio.create_task(recount.recount_once(dispatch_sessionmaker))
        await _waiting(owner_sessionmaker)
    await counting
    right = await truth(owner_sessionmaker, ready)
    assert right[0] == 2 and await counted(owner_sessionmaker, ready) == (right, right)


async def test_a_match_waits_for_a_recount_and_releases_after_it(
    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
    await drifted(owner_sessionmaker, ready)
    reached, release = await _held(monkeypatch, recount, "_after_recount_locked")
    counting = asyncio.create_task(recount.recount_once(dispatch_sessionmaker))
    await reached.wait()
    matcher = asyncio.create_task(matching.match_event(
        dispatch_sessionmaker, KEYS, matching.Verified(), tenant_id=ready.tenant_id, event_id=event_id,
        endpoint_id=ready.endpoint_id,
    ))  # fmt: skip
    await _waiting(owner_sessionmaker)
    release.set()
    await counting
    assert await matcher == "matched"
    right = await truth(owner_sessionmaker, ready)
    assert right[0] == 0 and await counted(owner_sessionmaker, ready) == (right, right)


async def test_a_recount_waits_for_a_match_and_counts_after_it(
    ready, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    [event_id] = await send(ingress_sessionmaker, ready, ALARM)
    await drifted(owner_sessionmaker, ready)
    reached, release = await _held(monkeypatch, matching, "_after_event_locked")
    matcher = asyncio.create_task(matching.match_event(
        dispatch_sessionmaker, KEYS, matching.Verified(), tenant_id=ready.tenant_id, event_id=event_id,
        endpoint_id=ready.endpoint_id,
    ))  # fmt: skip
    await reached.wait()
    counting = asyncio.create_task(recount.recount_once(dispatch_sessionmaker))
    await _waiting(owner_sessionmaker)
    release.set()
    assert await matcher == "matched"
    await counting
    right = await truth(owner_sessionmaker, ready)
    assert right[0] == 0 and await counted(owner_sessionmaker, ready) == (right, right)


async def test_a_correction_rolled_back_is_never_warned(ready, owner_sessionmaker, ingress_sessionmaker,
                                                        dispatch_sessionmaker, monkeypatch) -> None:  # fmt: skip
    """The owner's M3 review: drift is warned about once its correction has committed, never before."""
    await send(ingress_sessionmaker, ready, ALARM)
    await drifted(owner_sessionmaker, ready)
    before = await counted(owner_sessionmaker, ready)

    async def fail() -> None:
        raise RuntimeError("the commit never happens")

    monkeypatch.setattr(recount, "_before_recount_commit", fail, raising=False)
    with structlog.testing.capture_logs() as logs:
        assert await recount.recount_once(dispatch_sessionmaker) == {"error": 1}
    assert [e for e in logs if e["event"] == "event_counters_drifted"] == []
    assert await counted(owner_sessionmaker, ready) == before
