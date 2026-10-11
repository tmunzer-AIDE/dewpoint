# SPDX-License-Identifier: Apache-2.0
"""The deployment's ingress budget (the owner's ruling on 2b-4b's M3 checkpoint 4): an atomic deployment-wide limit on
outstanding work, shared fairly. A tenant's outstanding work is its pending events' credit (each, its endpoint's
enabled bindings when accepted) and its webhook requests still queued or starting; the deployment's is their sum.
Ingress admits a delivery only within its room (the limit but what's kept for top-ups), each tenant within its share
(that room over the tenants with work outstanding once it's admitted and one more) and all of them keeping that share
free for a tenant yet to come (a single event excepted: it can't be split), under the deployment's row: deliveries at
once never pass it. Matching turns an event's credit into its requests', a top-up only within the
limit; every way out of pending, of queued or starting, or of the tables releases it. Accept-to-start times are
measured by the probes, never promised."""

import asyncio
import uuid
from typing import Any

import pytest
import structlog
from sqlalchemy import text

from dewpoint.apps.dispatcher import dispatch, matching, recount
from tests.apps.dispatcher.inbound import bind, inbound, sealed
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.test_admission import KEYS, OPEN_GRAPH
from tests.apps.test_runs import FakeClient
from tests.apps.test_workflow_ops import create, publish
from tests.core.ingress.support import RECORD
from tests.support.starting import mark_starting

pytestmark = pytest.mark.usefixtures("development_deployment")
ALARM = {"type": "ap_down", "site": "s-1"}


async def limited(owner: Any, limit: int) -> None:
    """The deployment's limit: its capacity's three values, multiplied."""
    async with owner() as s, s.begin():
        await s.execute(text("update platform_settings set ingress_starts_per_s = :q, ingress_headroom = 1, "
                             "ingress_queue_wait_s = 1"), {"q": limit})  # fmt: skip


async def a_tenant(stack: tuple[Any, ...], fan_out: int, *, filtered: int = 0) -> Any:
    """A tenant whose endpoint has `fan_out` enabled bindings, each to a workflow of its own (`filtered` of them
    matching no alarm)."""
    owner, api, admin, dispatch_, settings = stack
    ready = await inbound(owner, api, admin, dispatch_, settings)
    for k in range(fan_out):
        workflow = ready.workflow_id
        if k:
            workflow = await create(api, ready.ctx, OPEN_GRAPH, name=f"fan-{k}")
            assert (await publish(api, ready.ctx, workflow, settings)).version is not None
        never = [{"pointer": "/type", "value": "nothing"}] if k < filtered else None
        await bind(owner, ready, workflow, filter=never)
    return ready


async def deliver(ingress: Any, ready: Any, n: int = 1, endpoint_id: uuid.UUID | None = None) -> dict[str, Any]:
    """`n` events in one delivery: its outcome."""
    ids = [uuid.uuid4() for _ in range(n)]
    params = {"e": endpoint_id or ready.endpoint_id, "refusal": None, "read": 0, "ids": ids,
              "sealed": [sealed(ready, i, ALARM, endpoint_id=endpoint_id) for i in ids], "versions": [1] * n,
              "dedupe": [None] * n, "digests": [None] * n}  # fmt: skip
    async with ingress() as s, s.begin():
        return dict((await s.execute(RECORD, params)).scalar_one())


async def budget(owner: Any) -> tuple[int, int]:
    """The deployment's outstanding work and its tenants with any."""
    async with owner() as s:
        return tuple((await s.execute(text("select outstanding, active from ingress_budget"))).one())  # type: ignore[return-value]


async def owed(owner: Any, tenant: uuid.UUID) -> int:
    async with owner() as s:
        found = await s.execute(text("select outstanding from ingress_outstanding where tenant_id = :t"),
                                {"t": tenant})  # fmt: skip
        return int(found.scalar_one())


async def truth(owner: Any) -> int:
    """What the counters must say: pending events' credit and webhook requests queued or starting."""
    async with owner() as s:
        found = await s.execute(text(
            "select (select coalesce(sum(credit), 0) from inbound_events where status = 'pending') + (select count(*) "
            "from run_requests where source = 'webhook' and status in ('queued', 'starting'))"))  # fmt: skip
        return int(found.scalar_one())


async def exact(owner: Any) -> int:
    """The deployment's outstanding work, checked against the tenants' and the truth."""
    outstanding, active = await budget(owner)
    async with owner() as s:
        tenants = (await s.execute(text("select coalesce(sum(outstanding), 0), count(*) filter (where outstanding > 0) "
                                        "from ingress_outstanding"))).one()  # fmt: skip
    assert (outstanding, active) == (int(tenants[0]), int(tenants[1])) and outstanding == await truth(owner)
    return outstanding


@pytest.fixture
def stack(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    return owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings


async def test_deliveries_at_once_from_tenants_of_mixed_fan_out_never_pass_the_limit(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:  # fmt: skip
    """The invariant: 40 deliveries at once from three tenants (fan-outs 1, 5 and 20) against a limit of 100, 81 for
    ingress. Then their events matched and their requests started: the counters equal the truth after each."""
    await limited(owner_sessionmaker, 100)
    tenants = [await a_tenant(stack, fan_out) for fan_out in (1, 5, 20)]
    outcomes = await asyncio.gather(*(deliver(ingress_sessionmaker, tenants[k % 3], 1 + k % 2) for k in range(40)))
    kinds = {o["outcome"] for o in outcomes}
    assert kinds == {"recorded", "backlog_full"}, outcomes
    assert await exact(owner_sessionmaker) <= 81
    await workers(owner_sessionmaker)
    for _ in range(3):
        await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified())
        assert await exact(owner_sessionmaker) <= 100
        await dispatch.dispatch_once(dispatch_sessionmaker, FakeClient(), KEYS, api_settings, BUILD,
                                     dispatch.Rotation())  # fmt: skip
        assert await exact(owner_sessionmaker) <= 100


async def test_idle_tenants_delivering_at_once_share_the_limits_room_never_past_it(
    stack, owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    """Six tenants with nothing outstanding delivering at once, each delivery worth 5, against the least limit, 40, of
    which ingress fills 21: admitted one at a time, each keeping a share free for the next (10, 7, 5 kept), three get
    in, whichever; the fourth's share, 4, is less than its 5."""
    await limited(owner_sessionmaker, 20)
    tenants = [await a_tenant(stack, 5) for _ in range(6)]
    outcomes = await asyncio.gather(*(deliver(ingress_sessionmaker, ready) for ready in tenants))
    assert sorted(o["outcome"] for o in outcomes) == ["backlog_full"] * 3 + ["recorded"] * 3, outcomes
    assert await exact(owner_sessionmaker) == 15 and (await budget(owner_sessionmaker))[1] == 3


async def test_a_tenant_with_work_outstanding_is_admitted_only_within_its_share(
    stack, owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    """Its share: ingress's room over the tenants with work outstanding and one more, half of it when it's alone. A
    limit of 100: 81 for ingress."""
    await limited(owner_sessionmaker, 100)
    wide, middle = await a_tenant(stack, 20), await a_tenant(stack, 5)
    assert (await deliver(ingress_sessionmaker, wide, 2))["outcome"] == "recorded"  # 40: its first, alone, 40 at most
    refused = await deliver(ingress_sessionmaker, wide)  # 60 > its share alone, 40
    assert refused["outcome"] == "backlog_full" and refused["retry_after"] >= 1
    assert (await deliver(ingress_sessionmaker, middle))["outcome"] == "recorded"  # 45
    assert (await deliver(ingress_sessionmaker, middle))["outcome"] == "recorded"  # its 10 within 81 over 3, 27
    assert await owed(owner_sessionmaker, wide.tenant_id) == 40 and await exact(owner_sessionmaker) == 50
    assert (await budget(owner_sessionmaker))[1] == 2


async def test_freed_credit_goes_to_a_tenant_under_its_share_never_to_one_past_it(
    stack, owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    """A tenant holding more than its share (admitted while it was alone) gets nothing more when credit is freed until
    it's under its share; others under theirs come in. A limit of 100, 81 for ingress."""
    await limited(owner_sessionmaker, 100)
    wide, middle = await a_tenant(stack, 20), await a_tenant(stack, 5)
    filler, narrow = await a_tenant(stack, 1), await a_tenant(stack, 1)
    assert (await deliver(ingress_sessionmaker, wide, 2))["outcome"] == "recorded"  # 40, alone
    assert (await deliver(ingress_sessionmaker, middle, 2))["outcome"] == "recorded"  # 50
    assert (await deliver(ingress_sessionmaker, filler, 11))["outcome"] == "recorded"  # 61: 20 kept
    async with owner_sessionmaker() as s, s.begin():  # one of the wide tenant's events cancelled: 20 freed
        await s.execute(text("update inbound_events set status = 'cancelled', reason = 'user_cancelled', "
                             "ended_at = now() where id = (select id from inbound_events where tenant_id = :t "
                             "limit 1)"), {"t": wide.tenant_id})  # fmt: skip
    assert (await deliver(ingress_sessionmaker, wide))["outcome"] == "backlog_full"  # 40 > its share, 81 over 4: 20
    assert (await deliver(ingress_sessionmaker, narrow, 2))["outcome"] == "recorded"  # its first, within 16
    assert (await deliver(ingress_sessionmaker, middle))["outcome"] == "recorded"  # its 15 within its 16
    assert await exact(owner_sessionmaker) == 48


EVENT_EXITS = {  # how a pending event leaves: each releases its credit
    "cancelled": "update inbound_events set status = 'cancelled', reason = 'user_cancelled', ended_at = now() "
                 "where tenant_id = :t",
    "dead": "update inbound_events set status = 'dead', reason = 'event_not_json', ended_at = now() "
            "where tenant_id = :t",
    "deleted": "delete from inbound_events where tenant_id = :t",
}  # fmt: skip
# How a queued webhook request leaves, each releasing 1 (and `started`, below). Never `refused`: that's a request never
# admitted, refused as it was recorded, with no envelope (0017's check)
REQUEST_EXITS = {
    "cancelled": "update run_requests set status = 'cancelled', reason = 'user_cancelled', ended_at = now() "
                 "where tenant_id = :t",
    "dead": "update run_requests set status = 'dead', reason = 'start_refused', ended_at = now() where tenant_id = :t",
    "deleted": "delete from run_requests where tenant_id = :t",
}  # fmt: skip


@pytest.mark.parametrize("exit", EVENT_EXITS)
async def test_a_pending_event_releases_its_credit_however_it_leaves(
    stack, owner_sessionmaker, ingress_sessionmaker, exit: str
) -> None:  # fmt: skip
    ready = await a_tenant(stack, 5)
    await deliver(ingress_sessionmaker, ready, 2)
    assert await exact(owner_sessionmaker) == 10
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text(EVENT_EXITS[exit]), {"t": ready.tenant_id})
    assert await exact(owner_sessionmaker) == 0 and (await budget(owner_sessionmaker))[1] == 0


@pytest.mark.parametrize("exit", REQUEST_EXITS)
async def test_a_queued_webhook_request_releases_its_credit_however_it_leaves(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, exit: str
) -> None:  # fmt: skip
    ready = await a_tenant(stack, 3, filtered=1)  # 3 bindings, one never matching
    await deliver(ingress_sessionmaker, ready)
    assert await exact(owner_sessionmaker) == 3
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {"matched": 1}
    assert await exact(owner_sessionmaker) == 2  # the binding it didn't match: released
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text(REQUEST_EXITS[exit]), {"t": ready.tenant_id})
    assert await exact(owner_sessionmaker) == 0


async def test_a_started_request_releases_its_credit_and_a_start_put_back_keeps_it(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:  # fmt: skip
    ready = await a_tenant(stack, 2)
    await deliver(ingress_sessionmaker, ready)
    await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified())
    async with owner_sessionmaker() as s, s.begin():  # a start found absent goes back to the queue: still outstanding
        found = await s.execute(text("select id from run_requests where tenant_id = :t"), {"t": ready.tenant_id})
        for (request_id,) in found.all():
            await mark_starting(s, request_id)
        await s.execute(text("update run_requests set status = 'queued', starting_at = null where tenant_id = :t"),
                        {"t": ready.tenant_id})  # fmt: skip
    assert await exact(owner_sessionmaker) == 2
    await workers(owner_sessionmaker)
    assert await dispatch.dispatch_once(dispatch_sessionmaker, FakeClient(), KEYS, api_settings, BUILD,
                                        dispatch.Rotation()) == {"started": 2}  # fmt: skip
    assert await exact(owner_sessionmaker) == 0


async def test_bindings_added_before_matching_take_a_top_up_only_within_the_limit(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    """An event keeps the credit it was accepted with; bindings added since need the limit's room, else it waits. The
    least limit, 40: two events of credit 1 grown to 20 bindings beside 7 of another tenant's: the first's top-up
    fits (28), the second's doesn't (47) until the other's requests leave."""
    await limited(owner_sessionmaker, 40)
    ready, other = await a_tenant(stack, 1), await a_tenant(stack, 1)
    await deliver(ingress_sessionmaker, ready, 2)  # their credit: 1 each
    await widened(stack, ready, 19)  # 20 bindings: 19 more each
    assert (await deliver(ingress_sessionmaker, other, 7))["outcome"] == "recorded"  # 9
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {
        "backlog_full": 1, "matched": 8,
    }  # fmt: skip
    assert await exact(owner_sessionmaker) == 28  # its first event's 20 requests, its second pending, the other's 7
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("delete from run_requests where tenant_id = :t"), {"t": other.tenant_id})
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {"matched": 1}
    assert await exact(owner_sessionmaker) == 40  # its 40 requests


async def widened(stack: tuple[Any, ...], ready: Any, n: int) -> None:
    """`n` bindings more on its endpoint, each to a workflow of its own."""
    for k in range(n):
        workflow = await create(stack[1], ready.ctx, OPEN_GRAPH, name=f"added-{k}")
        assert (await publish(stack[1], ready.ctx, workflow, stack[4])).version is not None
        await bind(stack[0], ready, workflow)


async def test_matchers_at_once_never_pass_the_limit_with_their_top_ups(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:  # fmt: skip
    """Four dispatchers' passes at once over four tenants (whose counter rows don't serialize them), each match held a
    moment once it has its event: each event's 2 bindings added since take the limit's room under the budget's row,
    which holds whoever matches. 17 events of credit 1, a limit of 40: 11 matches fit (39), 6 events wait."""
    await limited(owner_sessionmaker, 40)

    async def held() -> None:
        await asyncio.sleep(0.05)

    monkeypatch.setattr(matching, "_after_event_locked", held)
    tenants = [await a_tenant(stack, 1) for _ in range(4)]
    for ready, n in zip(tenants, (5, 5, 5, 2), strict=True):  # each keeping the next one's share free
        assert (await deliver(ingress_sessionmaker, ready, n))["outcome"] == "recorded"
        await widened(stack, ready, 2)
    assert await exact(owner_sessionmaker) == 17
    for _ in range(3):
        await asyncio.gather(*(matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified())
                               for _ in range(4)))  # fmt: skip
        assert await exact(owner_sessionmaker) <= 40
    async with owner_sessionmaker() as s:
        found = await s.execute(text("select status, count(*) from inbound_events group by status"))
        assert dict(found.all()) == {"matched": 11, "pending": 6}
    assert await exact(owner_sessionmaker) == 39


async def test_bindings_disabled_before_matching_release_the_credit_they_took(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    ready = await a_tenant(stack, 3)
    await deliver(ingress_sessionmaker, ready)
    assert await exact(owner_sessionmaker) == 3
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update trigger_bindings set enabled = false where tenant_id = :t and workflow_id <> :w"),
                        {"t": ready.tenant_id, "w": ready.workflow_id})  # fmt: skip
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {"matched": 1}
    assert await exact(owner_sessionmaker) == 1


async def test_a_tenants_counters_deleted_take_its_work_and_its_place_with_them(
    stack, owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    """An erasure deletes a tenant's rows in whatever order: the deployment's counters end as if it never was."""
    gone, kept = await a_tenant(stack, 5), await a_tenant(stack, 1)
    await deliver(ingress_sessionmaker, gone, 2)
    await deliver(ingress_sessionmaker, kept)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("delete from tenant_event_counters where tenant_id = :t"), {"t": gone.tenant_id})
        await s.execute(text("delete from inbound_events where tenant_id = :t"), {"t": gone.tenant_id})
    assert await budget(owner_sessionmaker) == (1, 1)


async def test_the_leader_finds_any_drift_between_the_counters_and_the_truth(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    ready = await a_tenant(stack, 5)
    await deliver(ingress_sessionmaker, ready)
    async with dispatch_sessionmaker() as s:
        assert tuple((await s.execute(text("select counted, actual from ingress_budget_drift()"))).one()) == (5, 5)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update ingress_budget set outstanding = 7"))
    async with dispatch_sessionmaker() as s:
        assert tuple((await s.execute(text("select counted, actual from ingress_budget_drift()"))).one()) == (7, 5)


async def test_a_transaction_releasing_many_tenants_work_takes_the_budget_only_at_its_commit(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    """A plugin's retirement cancels many tenants' requests in one transaction. It holds their rows, never the budget,
    until it commits: a delivery meanwhile (its tenant's counter row, then the budget) never waits on it, and so the
    two can never wait on each other."""
    first, second = await a_tenant(stack, 1), await a_tenant(stack, 1)
    await deliver(ingress_sessionmaker, first)
    await deliver(ingress_sessionmaker, second)
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {"matched": 2}
    async with owner_sessionmaker() as bulk, bulk.begin():
        await bulk.execute(text("update run_requests set status = 'cancelled', reason = 'node_type_retired', "
                                "ended_at = now() where tenant_id = any(:t)"),
                           {"t": [first.tenant_id, second.tenant_id]})  # fmt: skip
        delivered = await asyncio.wait_for(deliver(ingress_sessionmaker, second), timeout=10)
        assert delivered["outcome"] == "recorded"
    assert await exact(owner_sessionmaker) == 1  # the new event's credit; the cancelled requests' released


async def test_the_leader_alerts_on_the_budgets_drift_at_most_once_a_minute(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:  # fmt: skip
    """Never corrected there: the counters move only with the work; a difference is a defect to find."""
    ready = await a_tenant(stack, 5)
    await deliver(ingress_sessionmaker, ready)
    clock = [1_000.0]
    monkeypatch.setattr(recount.time, "monotonic", lambda: clock[0])
    drift = recount.Drift()
    assert await recount.check_budget(dispatch_sessionmaker, drift) == {"checked": 1}
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update ingress_budget set outstanding = 7"))
    with structlog.testing.capture_logs() as logs:
        assert await recount.check_budget(dispatch_sessionmaker, drift) == {}  # within the minute: not yet
        clock[0] += recount.DRIFT_S
        assert await recount.check_budget(dispatch_sessionmaker, drift) == {"drifted": 1}
    assert [(e["event"], e["counted"], e["actual"]) for e in logs] == [("ingress_budget_drift", 7, 5)]


async def test_requests_queued_by_a_matcher_that_never_asks_the_budget_are_counted_all_the_same(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:  # fmt: skip
    """A dispatcher still on the code before 0050 (an upgrade rolling out) queues requests without asking: they're
    counted as they're inserted, whoever inserts them, so the budget stays exact and its releases never undercount."""
    ready = await a_tenant(stack, 3)
    await deliver(ingress_sessionmaker, ready)
    asked = "SELECT cast(:credit AS bigint) + cast(:k AS bigint) >= 0"  # always yes
    monkeypatch.setattr(matching, "MATCHED", text(asked))
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {"matched": 1}
    assert await exact(owner_sessionmaker) == 3


async def test_tenants_at_once_keep_to_their_shares_and_leave_a_newcomer_room(
    stack, owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    """The fresh review 5's I3 and the load probe's finding: three tenants delivering at once, a round at a time, until
    each is refused, hold a share each, the room ingress may fill over the tenants with work outstanding and one more:
    so one more still finds room. A limit of 100, of which ingress fills 81 (19 kept for top-ups): 20 each, and a
    newcomer's event of 5 bindings fits beside them (16 kept). Then their share is 81 over 5, 16: none of them is
    admitted again."""
    await limited(owner_sessionmaker, 100)
    steady = [await a_tenant(stack, 1) for _ in range(3)]
    newcomer = await a_tenant(stack, 5)
    for _ in range(40):
        outcomes = await asyncio.gather(*(deliver(ingress_sessionmaker, ready) for ready in steady))
        if all(o["outcome"] == "backlog_full" for o in outcomes):
            break
    assert [await owed(owner_sessionmaker, ready.tenant_id) for ready in steady] == [20, 20, 20]
    late = await asyncio.gather(deliver(ingress_sessionmaker, newcomer),
                                *(deliver(ingress_sessionmaker, ready) for ready in steady))  # fmt: skip
    assert [o["outcome"] for o in late] == ["recorded"] + ["backlog_full"] * 3, late
    assert await exact(owner_sessionmaker) == 65 and (await budget(owner_sessionmaker))[1] == 4


async def test_a_delivery_that_can_never_fit_is_refused_for_good(
    stack, owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    """The fresh review 5's I1: one worth more than a tenant may hold even alone in an otherwise empty deployment (half
    of ingress's room, for more than one event: the owner's ruling on the M3 checkpoint 5) would get a 429 for ever;
    it's refused as too large, nothing stored."""
    await limited(owner_sessionmaker, 40)  # 21 for ingress: 10 at most for several events
    ready = await a_tenant(stack, 1)
    assert await deliver(ingress_sessionmaker, ready, 11) == {"outcome": "over_limit"}
    assert (await deliver(ingress_sessionmaker, ready, 10))["outcome"] == "recorded"
    assert await exact(owner_sessionmaker) == 10


async def test_while_ingress_fills_the_deployment_a_top_up_still_finds_room(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    """The fresh review 5's I2: ingress never fills what's kept for top-ups (an event's most bindings but the one its
    credit holds), so an event whose bindings grew since it was accepted is matched however busy ingress keeps the
    deployment, never starved behind deliveries taking each unit a start frees. Three tenants deliver until ingress
    refuses them all; the top-up still fits."""
    await limited(owner_sessionmaker, 40)  # 21 for ingress
    ready = await a_tenant(stack, 1)
    fillers = [await a_tenant(stack, 1) for _ in range(3)]
    await deliver(ingress_sessionmaker, ready)
    await widened(stack, ready, 1)
    for _ in range(30):
        outcomes = [(await deliver(ingress_sessionmaker, filler))["outcome"] for filler in fillers]
        if outcomes == ["backlog_full"] * 3:
            break
    filled = await exact(owner_sessionmaker)
    assert filled <= 21
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {"matched": filled}
    assert await exact(owner_sessionmaker) == filled + 1  # its two requests for its credit of 1


async def test_no_tenant_nor_tenants_arriving_one_after_another_take_the_room_from_a_newcomer(
    stack, owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    """The owner's ruling on the M3 checkpoint 5 and the fresh review 6's I2: a tenant with nothing outstanding could
    take all of ingress's room (81 of a limit of 100), and a newcomer then not even 1; first admissions one after
    another could too (40, 27 and 14). Every admission now keeps one share free for a tenant yet to come: each holds at
    most the room over the tenants with work outstanding once it's admitted and one more, and all of them together at
    most the room but that share. Alone: 40. Past what a tenant could hold even alone in an otherwise empty deployment:
    413, for good."""
    await limited(owner_sessionmaker, 100)  # 81 for ingress
    first, second, third, fourth, fifth = [await a_tenant(stack, 1) for _ in range(5)]
    assert await deliver(ingress_sessionmaker, first, 81) == {"outcome": "over_limit"}
    assert await deliver(ingress_sessionmaker, first, 41) == {"outcome": "over_limit"}
    assert (await deliver(ingress_sessionmaker, first, 40))["outcome"] == "recorded"  # 41 kept: 40 for the next
    assert (await deliver(ingress_sessionmaker, first))["outcome"] == "backlog_full"  # past its share alone, 40
    assert (await deliver(ingress_sessionmaker, second, 15))["outcome"] == "backlog_full"  # 27 kept: 54 at most
    assert (await deliver(ingress_sessionmaker, second, 14))["outcome"] == "recorded"
    assert (await deliver(ingress_sessionmaker, third, 8))["outcome"] == "backlog_full"  # 20 kept: 61 at most
    assert (await deliver(ingress_sessionmaker, third, 7))["outcome"] == "recorded"
    assert (await deliver(ingress_sessionmaker, fourth, 4))["outcome"] == "recorded"  # 16 kept: 65
    assert (await deliver(ingress_sessionmaker, fifth, 3))["outcome"] == "recorded"  # 13 kept: 68
    assert await exact(owner_sessionmaker) == 68


async def test_only_a_single_event_takes_more_than_its_tenants_share_never_a_delivery_of_several(
    stack, owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    """The fresh review 6's I1: what a first admission may hold past its share is one event's credit (an event can't
    be split), never 20 for any delivery. Four tenants holding 1 each (81 for ingress): a newcomer's share is 81 over 7,
    11; four events of 5 bindings (20) don't come in, one event of 20 bindings does (13 still kept)."""
    await limited(owner_sessionmaker, 100)
    for ready in [await a_tenant(stack, 1) for _ in range(4)]:
        assert (await deliver(ingress_sessionmaker, ready))["outcome"] == "recorded"
    middle, wide = await a_tenant(stack, 5), await a_tenant(stack, 20)
    assert (await deliver(ingress_sessionmaker, middle, 4))["outcome"] == "backlog_full"
    assert (await deliver(ingress_sessionmaker, wide))["outcome"] == "recorded"
    assert await exact(owner_sessionmaker) == 24


async def test_at_the_least_limit_an_event_of_twenty_bindings_needs_a_deployment_holding_nothing_else(
    stack, owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    """The owner's ruling on the M3 checkpoint 5: whatever bounds a first admission, an event of an endpoint's most
    bindings stays admissible at the least limit (40, 21 for ingress), but only into a deployment holding nothing
    else: no room is reserved for it, so while another tenant keeps work outstanding it waits (the fresh review 6's
    I3, a known limit)."""
    await limited(owner_sessionmaker, 40)
    wide, other = await a_tenant(stack, 20), await a_tenant(stack, 1)
    assert (await deliver(ingress_sessionmaker, other, 5))["outcome"] == "recorded"
    assert (await deliver(ingress_sessionmaker, wide))["outcome"] == "backlog_full"  # 25 > 21 but the 7 kept: waits
    async with owner_sessionmaker() as s, s.begin():  # the other's work leaves: the deployment holds nothing
        await s.execute(text("update inbound_events set status = 'cancelled', reason = 'user_cancelled', "
                             "ended_at = now() where tenant_id = :t"), {"t": other.tenant_id})  # fmt: skip
    assert (await deliver(ingress_sessionmaker, wide))["outcome"] == "recorded"
    assert (await deliver(ingress_sessionmaker, wide))["outcome"] == "backlog_full"  # its share: 10
    assert await deliver(ingress_sessionmaker, wide, 2) == {"outcome": "over_limit"}  # 40: never, even alone
    async with owner_sessionmaker() as s, s.begin():  # its event leaves pending: nothing outstanding
        await s.execute(text("update inbound_events set status = 'cancelled', reason = 'user_cancelled', "
                             "ended_at = now() where tenant_id = :t"), {"t": wide.tenant_id})  # fmt: skip
    assert (await deliver(ingress_sessionmaker, wide))["outcome"] == "recorded"


async def test_idle_tenants_asking_at_once_keep_a_share_free_whoever_comes_first(
    stack, owner_sessionmaker, ingress_sessionmaker
) -> None:  # fmt: skip
    """Four tenants with nothing outstanding asking 40 each at once (81 for ingress): whichever comes first gets it,
    alone; the others' shares are then 27, so none. Then the three ask 7 each at once, beside the first asking more:
    all three get in, each keeping a share free for the next (27, 20, 16 kept: 61), and the first tenant, past its
    share, doesn't."""
    await limited(owner_sessionmaker, 100)
    tenants = [await a_tenant(stack, 1) for _ in range(4)]
    asked = await asyncio.gather(*(deliver(ingress_sessionmaker, ready, 40) for ready in tenants))
    assert sorted(o["outcome"] for o in asked) == ["backlog_full"] * 3 + ["recorded"], asked
    first = tenants[[o["outcome"] for o in asked].index("recorded")]
    others = [ready for ready in tenants if ready is not first]
    again = await asyncio.gather(deliver(ingress_sessionmaker, first),
                                 *(deliver(ingress_sessionmaker, ready, 7) for ready in others))  # fmt: skip
    assert [o["outcome"] for o in again] == ["backlog_full"] + ["recorded"] * 3, again
    assert await exact(owner_sessionmaker) == 61


async def test_a_capacity_change_waits_for_an_admission_in_flight_and_counts_it(
    stack, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker
) -> None:  # fmt: skip
    """The owner's ruling on the M3 checkpoint 5: a change taking the limit to 45 while 30 are outstanding and a
    delivery of 20 is being admitted. It waits for that admission's commit, counts its 20, and refuses: never a limit
    of 45 under 50 outstanding."""
    from dewpoint.core.auth.users import create_user
    from dewpoint.core.platform import service

    await limited(owner_sessionmaker, 100)
    held, arriving = await a_tenant(stack, 1), await a_tenant(stack, 1)
    assert (await deliver(ingress_sessionmaker, held, 30))["outcome"] == "recorded"
    async with owner_sessionmaker() as s, s.begin():
        actor = (await create_user(s, email=f"{uuid.uuid4().hex[:8]}@corp.test", password="violet-otter-canyon-42")).id

    async def lowered() -> None:
        async with api_sessionmaker() as s, s.begin():
            await service.set_ingress_capacity(s, change={"starts_per_s": 45.0}, attestation="Measured.",
                                               actor_id=actor)  # fmt: skip

    ids = [uuid.uuid4() for _ in range(20)]
    params = {"e": arriving.endpoint_id, "refusal": None, "read": 0, "ids": ids,
              "sealed": [sealed(arriving, i, ALARM) for i in ids], "versions": [1] * 20, "dedupe": [None] * 20,
              "digests": [None] * 20}  # fmt: skip
    async with ingress_sessionmaker() as s:
        async with s.begin():
            assert (await s.execute(RECORD, params)).scalar_one()["outcome"] == "recorded"  # the budget's row held
            change = asyncio.create_task(lowered())
            await asyncio.sleep(1.0)
            assert not change.done()  # waiting on the admission's row
    with pytest.raises(service.IngressCapacityBelowOutstandingError):
        await change
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select ingress_limit()"))).scalar_one() == 100
    assert await exact(owner_sessionmaker) == 50


async def test_a_matcher_that_never_asks_the_budget_still_cannot_commit_past_the_limit(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:  # fmt: skip
    """The owner's ruling on the M3 checkpoint 5: a matcher that queues an event's requests without asking (here, the
    check stubbed out) can't commit past the limit: the database refuses any commit adding past it, whoever wrote it.
    And the matcher takes that refusal as a full backlog (the ruling on M4's design: tolerant code, run in a release
    before the migration that brings the refusal): the event pending, its tenant passed by for the pass, so its later
    events keep their order. 10 outstanding of 40; three events of credit 1 grown to 20 bindings: the first fits (29),
    the second doesn't (48), the third waits behind it."""
    await limited(owner_sessionmaker, 40)
    ready, other = await a_tenant(stack, 1), await a_tenant(stack, 1)
    await deliver(ingress_sessionmaker, ready, 3)
    await widened(stack, ready, 19)
    assert (await deliver(ingress_sessionmaker, other, 7))["outcome"] == "recorded"
    monkeypatch.setattr(matching, "MATCHED", text("SELECT cast(:credit AS bigint) + cast(:k AS bigint) >= 0"))
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {
        "matched": 8, "backlog_full": 1, "busy_tenant": 1,
    }  # fmt: skip
    async with owner_sessionmaker() as s:
        found = await s.execute(text("select count(*) from inbound_events where status = 'pending'"))
        assert found.scalar_one() == 2
    assert await exact(owner_sessionmaker) == 29


async def test_a_commit_that_adds_nothing_net_goes_through_above_the_limit(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    """The fresh review 6's M1: with the count above the limit (drifted high, say: the leader only alerts), a match
    within its event's credit (its requests counted, its credit released) is no net addition and commits, so matching
    goes on; a delivery adding to it is refused."""
    await limited(owner_sessionmaker, 40)
    ready, other = await a_tenant(stack, 3), await a_tenant(stack, 1)
    await deliver(ingress_sessionmaker, ready)
    async with owner_sessionmaker() as s, s.begin():  # a drift, past every check (the bound's own included)
        await s.execute(text("set local session_replication_role = replica"))
        await s.execute(text("update ingress_budget set outstanding = outstanding + 50"))  # 53 > 40
    assert await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified()) == {"matched": 1}
    assert await budget(owner_sessionmaker) == (53, 1)
    assert (await deliver(ingress_sessionmaker, other))["outcome"] == "backlog_full"


async def test_a_capacity_change_waits_for_a_match_holding_the_budget_and_counts_its_top_up(
    stack, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, api_sessionmaker, monkeypatch
) -> None:  # fmt: skip
    """The fresh review 6's F: a match taking a top-up holds the budget's row from its check to its commit; a change
    lowering the limit to 50 meanwhile waits, then counts the match's 19 more (60 outstanding) and refuses."""
    from dewpoint.core.auth.users import create_user
    from dewpoint.core.platform import service

    await limited(owner_sessionmaker, 100)
    ready, first, second = [await a_tenant(stack, 1) for _ in range(3)]
    await deliver(ingress_sessionmaker, ready)
    await widened(stack, ready, 19)
    assert (await deliver(ingress_sessionmaker, first, 25))["outcome"] == "recorded"
    assert (await deliver(ingress_sessionmaker, second, 15))["outcome"] == "recorded"  # 41
    async with owner_sessionmaker() as s, s.begin():
        actor = (await create_user(s, email=f"{uuid.uuid4().hex[:8]}@corp.test", password="violet-otter-canyon-42")).id
    checked, release = asyncio.Event(), asyncio.Event()

    async def held() -> None:
        checked.set()
        await release.wait()

    monkeypatch.setattr(matching, "_before_commit", held)

    async def lowered() -> None:
        async with api_sessionmaker() as s, s.begin():
            await service.set_ingress_capacity(s, change={"starts_per_s": 50.0}, attestation="Measured.",
                                               actor_id=actor)  # fmt: skip

    matched = asyncio.create_task(
        matching.match_event(
            dispatch_sessionmaker,
            KEYS,
            matching.Verified(),
            tenant_id=ready.tenant_id,
            event_id=await pending_of(owner_sessionmaker, ready),
            endpoint_id=ready.endpoint_id,
        )
    )
    await asyncio.wait_for(checked.wait(), 30)  # its top-up checked: the budget's row held
    change = asyncio.create_task(lowered())
    await asyncio.sleep(1.0)
    assert not change.done()
    release.set()
    assert await matched == "matched"
    with pytest.raises(service.IngressCapacityBelowOutstandingError):
        await change
    assert await exact(owner_sessionmaker) == 60


async def pending_of(owner: Any, ready: Any) -> uuid.UUID:
    async with owner() as s:
        found = await s.execute(text("select id from inbound_events where tenant_id = :t and status = 'pending'"),
                                {"t": ready.tenant_id})  # fmt: skip
        return uuid.UUID(str(found.scalar_one()))
