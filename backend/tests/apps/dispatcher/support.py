# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for the dispatcher's tests: the current build, its ready workers, one begin, and a request's state."""

import uuid
from typing import Any

from sqlalchemy import text

from dewpoint.apps.codec import data_converter
from dewpoint.apps.dispatcher import dispatch
from dewpoint.apps.dispatcher.observe import REQUIRED, Build
from dewpoint.apps.worker.deployment import this_build
from dewpoint.engine import ENGINE_ABI
from tests.apps.test_admission import KEYS

BUILD = Build(this_build(), ENGINE_ABI)


async def workers(owner: Any, *, capabilities: tuple[str, ...] = REQUIRED, healthy: bool = True) -> None:
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into worker_instances (instance_id, build_id, capabilities, healthy) values (:i, :b, :c, :h)"),
            {"i": uuid.uuid4(), "b": BUILD.build_id, "c": list(capabilities), "h": healthy},
        )


async def begin(
    dispatch_sessionmaker: Any, request: Any, settings: Any, *, keys: Any = KEYS, build: Build = BUILD
) -> Any:
    seal = dispatch.sealer(data_converter(keys), "default")
    return await dispatch.begin(
        dispatch_sessionmaker, seal, settings, keys, tenant_id=request.tenant_id, request_id=request.id, build=build
    )


async def state(owner: Any, request_id: uuid.UUID) -> dict[str, Any]:
    async with owner() as s:
        r = (await s.execute(text("select status, reason, attempts from run_requests where id = :i"),
                             {"i": request_id})).one()  # fmt: skip
        run = (await s.execute(text("select status, started_at, queued_at from runs where id = :i"),
                               {"i": request_id})).first()  # fmt: skip
        slot = (await s.execute(text("select count(*) from run_slots where run_id = :i"), {"i": request_id})).scalar()
    return {"request": tuple(r), "run": tuple(run) if run else None, "slot": slot}
