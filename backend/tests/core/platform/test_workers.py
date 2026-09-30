# SPDX-License-Identifier: Apache-2.0
"""Engine worker instances (engine 2b spec §2.7): each records its build, its capabilities and whether it's healthy;
the dispatcher reads them."""

import uuid

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
