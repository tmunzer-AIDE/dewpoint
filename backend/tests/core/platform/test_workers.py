# SPDX-License-Identifier: Apache-2.0
"""Engine worker instances (engine 2b spec §2.7): each records its build, its capabilities and whether it's healthy;
the dispatcher reads them."""

import uuid

import pytest
from sqlalchemy import select

from dewpoint.core.models.platform import WorkerInstance
from dewpoint.core.platform.service import record_worker


async def test_an_instance_records_itself_and_each_check_updates_its_row(
    worker_sessionmaker, dispatch_sessionmaker
) -> None:
    instance = uuid.uuid4()
    for healthy in (True, False):
        async with worker_sessionmaker() as s, s.begin():  # as the worker records it
            await record_worker(
                s, instance_id=instance, build_id="dewpoint-0.1.0+abi5", capabilities=("a", "b"), healthy=healthy
            )
    async with dispatch_sessionmaker() as s:  # as the dispatcher reads it (2b-2)
        [row] = (await s.execute(select(WorkerInstance))).scalars().all()
    assert (row.instance_id, row.build_id, row.capabilities, row.healthy) == (
        instance,
        "dewpoint-0.1.0+abi5",
        ["a", "b"],
        False,
    )
    assert row.checked_at >= row.started_at


BUILD = "dewpoint-0.2.0+abi6"
CAPABILITIES = ("cel_request_size_guard", "claim_check", "payload_codec")


async def instances(owner, *rows: tuple[str, tuple[str, ...], bool, int]) -> None:
    """Instance rows: their build, capabilities, health, and how many seconds ago they last checked."""
    from sqlalchemy import text

    async with owner() as s, s.begin():
        for build, capabilities, healthy, age in rows:
            await s.execute(
                text("insert into worker_instances (instance_id, build_id, capabilities, healthy, checked_at) "
                     "values (:i, :b, :c, :h, now() - make_interval(secs => :a))"),
                {"i": uuid.uuid4(), "b": build, "c": list(capabilities), "h": healthy, "a": age},
            )  # fmt: skip


async def problems(dispatch) -> list[str]:
    from dewpoint.core.platform.service import workers_ready

    async with dispatch() as s, s.begin():
        return await workers_ready(s, BUILD, CAPABILITIES)


async def test_the_current_build_is_ready_when_every_live_instance_is_healthy_and_capable(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """Engine 2b spec §2.7: every instance of the current build that checked in the last 90 seconds is healthy and
    holds every required capability, and at least one does. A stale row isn't a live instance; another build's
    instances don't count."""
    assert await problems(dispatch_sessionmaker) == ["No live engine worker instance of build dewpoint-0.2.0+abi6."]
    await instances(owner_sessionmaker, (BUILD, CAPABILITIES, True, 5), (BUILD, (), False, 600),
                    ("dewpoint-0.1.0+abi5", (), False, 1))  # fmt: skip
    assert await problems(dispatch_sessionmaker) == []


@pytest.mark.parametrize(("capabilities", "healthy"), [(CAPABILITIES, False), (("claim_check", "payload_codec"), True)])
async def test_one_live_instance_unhealthy_or_lacking_a_capability_holds_the_build(
    owner_sessionmaker, dispatch_sessionmaker, capabilities, healthy
) -> None:
    await instances(owner_sessionmaker, (BUILD, CAPABILITIES, True, 1), (BUILD, capabilities, healthy, 2))
    assert len(await problems(dispatch_sessionmaker)) == 1
