# SPDX-License-Identifier: Apache-2.0
"""`runs` and `run_steps` (spec §8, §10 projection): idempotent upserts under retries, sanitized messages, RLS."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service
from dewpoint.engine.runtime import projection
from tests.support.workflows import seed_workflow


def row(run_id: uuid.UUID, status: str, **extra: Any) -> dict[str, Any]:
    step = uuid.UUID(int=7)
    return {
        "run_id": run_id,
        "step_id": step,
        "iteration_key": "",
        "attempt": 1,
        "node_key": "a",
        "status": status,
        **extra,
    }


async def seeded_run(owner: Any, dispatch: Any) -> tuple[uuid.UUID, uuid.UUID]:
    tenant, wf, version = await seed_workflow(owner)
    async with dispatch() as s, s.begin():
        await tenant_scope(s, tenant)
        run = await service.insert_run(
            s, run_id=uuid.uuid4(), tenant_id=tenant, workflow_id=wf, version_id=version, mode="live"
        )
    return tenant, run.id


async def steps(sm: Any, tenant: uuid.UUID, run_id: uuid.UUID) -> list[Any]:
    async with sm() as s, s.begin():
        await tenant_scope(s, tenant)
        return await service.run_steps(s, run_id)


async def test_upserts_are_idempotent_and_a_late_running_row_never_wins(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    done = row(run_id, "succeeded", output_preview={"v": 1}, outcome="applied")
    for rows in ([row(run_id, "running")], [done], [done], [row(run_id, "running")]):  # a retried projection
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await service.upsert_steps(s, tenant, rows)
    [only] = await steps(owner_sessionmaker, tenant, run_id)
    assert (only.status, only.output_preview, only.outcome) == ("succeeded", {"v": 1}, "applied")


async def test_messages_are_sanitized(owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker) -> None:
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        await service.upsert_steps(s, tenant, [row(run_id, "failed", error_message="bad\x00\x1b[31mred" + "x" * 900)])
        await service.finish_run(s, run_id, status="failed", ended_at=datetime.now(UTC), error_message="a\x07b")
    [only] = await steps(owner_sessionmaker, tenant, run_id)
    assert only.error_message.startswith("bad  [31mred") and len(only.error_message) == service.MESSAGE_LIMIT
    async with owner_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        assert (await service.get_run(s, run_id)).error_message == "a b"  # type: ignore[union-attr]


async def test_deep_iterations_and_long_codes_are_stored(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    """A projection write must never fail on a length: keys nest, and nothing bounds a plugin's error codes."""
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    deep = "/".join(f"{'k' * 63}:9999" for _ in range(3))  # the deepest nesting, longest keys, last items: 206 chars
    code = "plugin.\x1b" + "c" * 900
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        await service.upsert_steps(s, tenant, [row(run_id, "failed", iteration_key=deep, error_code=code)])
        await service.finish_run(s, run_id, status="failed", ended_at=datetime.now(UTC), error_code=code)
    [only] = await steps(owner_sessionmaker, tenant, run_id)
    assert only.iteration_key == deep and only.error_code == service.sanitize(code)
    assert only.error_code.startswith("plugin. ") and len(only.error_code) == service.MESSAGE_LIMIT


async def test_rows_stay_in_their_tenant(owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker) -> None:
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    other, _ = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        await service.upsert_steps(s, tenant, [row(run_id, "running")])
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, other)
        assert await service.get_run(s, run_id) is None and await service.run_steps(s, run_id) == []
    async with worker_sessionmaker() as s, s.begin():  # no tenant at all: nothing visible
        assert await service.list_runs(s) == []
    with pytest.raises(DBAPIError):  # a row for another tenant is refused
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, other)
            await service.upsert_steps(s, tenant, [row(run_id, "running", node_key="b")])


async def test_runs_list_newest_first_and_page(owner_sessionmaker, dispatch_sessionmaker) -> None:
    tenant, wf, version = await seed_workflow(owner_sessionmaker)
    ids = []
    for _ in range(3):
        async with dispatch_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            run = await service.insert_run(
                s, run_id=uuid.uuid4(), tenant_id=tenant, workflow_id=wf, version_id=version, mode="live"
            )
            ids.append(run.id)
    async with owner_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        first = await service.list_runs(s, limit=2)
        rest = await service.list_runs(s, before=first[-1].started_at, limit=2)
    assert [r.id for r in first + rest] == ids[::-1]


async def test_previews_and_messages_hold_nothing_the_database_refuses(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    """Final review: Postgres refuses NUL in jsonb and text, and a lone surrogate isn't UTF-8. A refused write is
    retried forever, and the run behind it never ends. What it can't store becomes U+FFFD, a number JSON can't hold its
    name."""
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    data = {"k\x00ey": ["a\x00b", "c\ud800d"], "n": float("nan")}
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        await service.upsert_steps(
            s, tenant, [row(run_id, "failed", input_preview=data, output_preview="\x00", error_message="m\ud800")]
        )
        await service.finish_run(s, run_id, status="failed", ended_at=datetime.now(UTC), error_code="c\ud800")
    [only] = await steps(owner_sessionmaker, tenant, run_id)
    assert only.input_preview == {"k�ey": ["a�b", "c�d"], "n": "nan"}
    assert (only.output_preview, only.error_message) == ("�", "m�")
    async with owner_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        assert (await service.get_run(s, run_id)).error_code == "c�"  # type: ignore[union-attr]


HOSTILE: list[Any] = [
    "plain",
    "nul\x00 esc\x1b bell\x07 tab\t newline\n",
    "lone \ud800 and \udfff surrogates",
    "x" * 900,
    {"k\x00ey": ["a\ud800b", float("nan"), float("-inf"), 1.5, None, True, {"deep\ud801": "\x00"}]},
]


@pytest.mark.parametrize("value", HOSTILE)
def test_the_engine_sends_what_storage_writes(value: Any) -> None:
    """PR #9 review: the workflow sizes a projection by the rows it sends, so it normalizes them as storage will
    (`engine.runtime.projection` can't import `core`, nor `core` the engine): the same values, and a second pass
    changes nothing."""
    assert projection.storable(value) == service.storable(value)
    assert service.storable(projection.storable(value)) == projection.storable(value)
    if isinstance(value, str):
        assert projection.sanitize(value) == service.sanitize(value)
        assert service.sanitize(projection.sanitize(value)) == projection.sanitize(value)
