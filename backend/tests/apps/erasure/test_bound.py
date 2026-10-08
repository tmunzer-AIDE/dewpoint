# SPDX-License-Identifier: Apache-2.0
"""Step 9 (the 2b-4 outline's "Why every execution is gone"): an erasure that reached its bound holds, with a fixed
reason, until the final check may run and finds nothing; then it completes. What it holds on: the firing bound, which
stays unproven (the deleted-and-recreated token test fails, and ticks have no execution timeout since M3), so no
erasure completes until the owner rules on another design; a verified namespace-change boundary (D3g), recorded on the
erasure, and lost if the deployment loses it; the bound itself (the latest close plus 30 days, the earliest point for
the final check, never a deadline); the namespace's retention, at most 30 days. Anything the final check finds reopens
the erasure, alerting; so does anything the reconciliation after completion finds, on every pass, for good."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
import structlog
from sqlalchemy import text
from temporalio.client import Client

from dewpoint.apps.dispatcher import evidence
from dewpoint.apps.erasure import bound, process, temporal
from dewpoint.core.models.erasure import Stage
from tests.apps.erasure.support import erasing, populated
from tests.apps.erasure.test_stages import QUEUE, Leaf, record, serving, until
from tests.core.retention.support import sql

pytestmark = pytest.mark.usefixtures("development_deployment")
BOUNDARY = "self-hosted authorizer (test)"


async def at_bound(owner: Any, ingress: Any, api: Any, retention: Any, client: Client) -> dict[str, Any]:
    data = await populated(owner, ingress)
    await erasing(api, data["t"])
    assert await until(retention, client, data["t"], Stage.BOUND) == Stage.BOUND
    return data


async def verified(owner: Any, name: str = BOUNDARY) -> None:
    await sql(owner, "insert into namespace_boundaries (name) values (:n)", n=name)


async def past_bound(owner: Any, tenant: uuid.UUID) -> None:
    await sql(owner, "update tenant_erasures set check_after = now() - interval '1 second' where tenant_id = :t",
              t=tenant)  # fmt: skip


@pytest.fixture
def proven(monkeypatch: pytest.MonkeyPatch) -> None:
    """The firing bound taken as proven: the only way any test here reaches completion."""
    monkeypatch.setattr(bound, "FIRING_BOUND", "proven for the test")


async def held(retention: Any, client: Client, owner: Any, tenant: uuid.UUID) -> tuple[int | None, str, int]:
    with structlog.testing.capture_logs() as logs:
        at = await process.advance(retention, client, tenant)
    erasure = await record(owner, tenant)
    alerts = [e["reason"] for e in logs if e["event"] == "erasure_held" and e["log_level"] == "error"]
    assert alerts in ([], [erasure.failure])
    return at, erasure.failure, erasure.attempts


async def test_no_erasure_completes_while_the_firing_bound_is_unproven(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker
) -> None:
    data = await at_bound(owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker,
                          server.client)  # fmt: skip
    await verified(owner_sessionmaker)
    await past_bound(owner_sessionmaker, data["t"])
    assert await held(retention_sessionmaker, server.client, owner_sessionmaker, data["t"]) == (
        Stage.BOUND, "firing_bound_unproven", 0
    )  # fmt: skip
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select status from tenants where id = :t"), {"t": data["t"]})).scalar() == (
            "erasing"
        )  # fmt: skip


async def test_without_a_verified_boundary_it_holds_and_a_lost_one_holds_it_again(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, proven
) -> None:
    data = await at_bound(owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker,
                          server.client)  # fmt: skip
    assert (await held(retention_sessionmaker, server.client, owner_sessionmaker, data["t"]))[1] == (
        "boundary_unverified"
    )  # fmt: skip
    await verified(owner_sessionmaker)
    assert (await held(retention_sessionmaker, server.client, owner_sessionmaker, data["t"]))[1] == "bound_not_reached"
    assert (await record(owner_sessionmaker, data["t"])).boundary == BOUNDARY  # the boundary it relies on
    await sql(owner_sessionmaker, "update namespace_boundaries set lost_at = now()")
    await verified(owner_sessionmaker, "another boundary")
    await past_bound(owner_sessionmaker, data["t"])
    assert (await held(retention_sessionmaker, server.client, owner_sessionmaker, data["t"]))[1] == "boundary_lost"


async def test_the_final_check_waits_for_the_bound_and_a_retention_above_30_days(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, proven, monkeypatch
) -> None:
    data = await at_bound(owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker,
                          server.client)  # fmt: skip
    await verified(owner_sessionmaker)
    with structlog.testing.capture_logs() as logs:
        await process.advance(retention_sessionmaker, server.client, data["t"])
    erasure = await record(owner_sessionmaker, data["t"])
    assert (erasure.failure, erasure.next_attempt_at) == ("bound_not_reached", erasure.check_after)  # not before
    assert not [e for e in logs if e["log_level"] == "error"]  # waiting for the bound is no alert

    async def longer(_: Client) -> timedelta:
        return timedelta(days=31)

    monkeypatch.setattr(evidence, "namespace_retention", longer)
    await past_bound(owner_sessionmaker, data["t"])
    assert (await held(retention_sessionmaker, server.client, owner_sessionmaker, data["t"]))[1] == (
        "retention_above_bound"
    )  # fmt: skip


async def test_it_completes_once_the_final_check_finds_nothing(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, proven
) -> None:
    data = await at_bound(owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker,
                          server.client)  # fmt: skip
    await verified(owner_sessionmaker)
    await process.advance(retention_sessionmaker, server.client, data["t"])
    await past_bound(owner_sessionmaker, data["t"])
    assert await process.advance(retention_sessionmaker, server.client, data["t"]) == Stage.COMPLETE
    erasure = await record(owner_sessionmaker, data["t"])
    assert (erasure.step, erasure.completed_at is not None, erasure.failure) == (Stage.COMPLETE, True, None)
    async with owner_sessionmaker() as s:
        status = (await s.execute(text("select status from tenants where id = :t"), {"t": data["t"]})).scalar()
        items = (await s.execute(text("select count(*) from tenant_erasure_items where tenant_id = :t"),
                                 {"t": data["t"]})).scalar()  # fmt: skip
        known = (await s.execute(text("select count(*) from tenant_erasure_known where tenant_id = :t"),
                                 {"t": data["t"]})).scalar()  # fmt: skip
        entry = (await s.execute(text("select details from audit_log where action = 'tenant.erasure.complete' "
                                      "and tenant_id = :t"), {"t": data["t"]})).scalar_one()  # fmt: skip
    assert (status, items) == ("erased", 0) and known > 0  # the item rows go; the ids to reconcile stay
    assert entry["boundary"] == BOUNDARY and dict(entry["tables"])["runs"] == 2 and entry["items"] > 0
    assert entry["backups_until"] > entry["completed_at"]  # complete in backups once they've expired
    assert await process.erase_pass(retention_sessionmaker, server.client) == {}  # nothing left to carry on


async def test_an_execution_found_at_the_final_check_reopens_the_erasure_alerting(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, proven
) -> None:
    data = await at_bound(owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker,
                          server.client)  # fmt: skip
    await verified(owner_sessionmaker)
    await process.advance(retention_sessionmaker, server.client, data["t"])
    late = f"t:{data['t']}:run:{uuid.uuid4()}"  # a start that landed late
    async with serving(server.client):
        await server.client.start_workflow(Leaf.run, id=late, task_queue=QUEUE)
    for _ in range(100):  # visibility shows it
        if [w for w, _ in await temporal.listed(server.client, f"t:{data['t']}:") if w == late]:
            break
    await past_bound(owner_sessionmaker, data["t"])
    with structlog.testing.capture_logs() as logs:
        await process.advance(retention_sessionmaker, server.client, data["t"])
    assert [e["event"] for e in logs if e["log_level"] == "error"][:1] == ["erasure_incident"]
    erasure = await record(owner_sessionmaker, data["t"])
    assert (erasure.incidents, erasure.reopened_at is not None, erasure.completed_at) == (1, True, None)
    assert await until(retention_sessionmaker, server.client, data["t"], Stage.BOUND) == Stage.BOUND
    assert await temporal.execution(server.client, late, None) is None  # deleted, with its own bound
    erasure = await record(owner_sessionmaker, data["t"])
    assert erasure.check_after == erasure.latest_close + timedelta(days=30) and erasure.fenced_at is not None


async def test_a_schedule_found_after_completion_reopens_it_and_is_deleted(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, proven
) -> None:
    """A late create (the reconciliation after completion, on every pass): the schedule is found under a known id,
    paused, its firings inventoried, deleted; the erasure reopened, the tenant still erased, the fence still up."""
    from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

    data = await at_bound(owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker,
                          server.client)  # fmt: skip
    await verified(owner_sessionmaker)
    await process.advance(retention_sessionmaker, server.client, data["t"])
    await past_bound(owner_sessionmaker, data["t"])
    assert await process.advance(retention_sessionmaker, server.client, data["t"]) == Stage.COMPLETE
    async with owner_sessionmaker() as s:
        [schedule_id] = (await s.execute(text("select workflow_id from tenant_erasure_known where tenant_id = :t "
                                               "and kind = 'schedule'"), {"t": data["t"]})).scalars()  # fmt: skip
    await server.client.create_schedule(schedule_id, Schedule(
        action=ScheduleActionStartWorkflow(Leaf.run, id=schedule_id, task_queue=QUEUE),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
    ))  # fmt: skip
    assert await bound.reconcile_erased(retention_sessionmaker, server.client) == {"reopened": 1}
    erasure = await record(owner_sessionmaker, data["t"])
    assert (erasure.step, erasure.incidents, erasure.completed_at) == (Stage.PAUSE, 1, None)
    assert await until(retention_sessionmaker, server.client, data["t"], Stage.BOUND) == Stage.BOUND
    assert await temporal.schedule(server.client, schedule_id) is None
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select status from tenants where id = :t"), {"t": data["t"]})).scalar() == (
            "erased"
        )  # fmt: skip
    assert await bound.reconcile_erased(retention_sessionmaker, server.client) == {}  # open erasures aren't its


async def test_a_schedule_found_at_the_final_check_is_paused_and_deleted(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, proven
) -> None:
    """A late create the final check finds reopens the erasure from stage 31: paused, inventoried, then deleted, so
    the next final check finds nothing (the review's finding 2: it stayed, the incident looping every bound)."""
    from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

    data = await at_bound(owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker,
                          server.client)  # fmt: skip
    await verified(owner_sessionmaker)
    await process.advance(retention_sessionmaker, server.client, data["t"])
    async with owner_sessionmaker() as s:
        [schedule_id] = (await s.execute(text("select workflow_id from tenant_erasure_known where tenant_id = :t "
                                               "and kind = 'schedule'"), {"t": data["t"]})).scalars()  # fmt: skip
    await server.client.create_schedule(schedule_id, Schedule(
        action=ScheduleActionStartWorkflow(Leaf.run, id=schedule_id, task_queue=QUEUE),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
    ))  # fmt: skip
    await past_bound(owner_sessionmaker, data["t"])
    assert await until(retention_sessionmaker, server.client, data["t"], Stage.BOUND) == Stage.BOUND
    assert (await record(owner_sessionmaker, data["t"])).incidents == 1
    assert await temporal.schedule(server.client, schedule_id) is None
