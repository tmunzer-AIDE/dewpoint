# SPDX-License-Identifier: Apache-2.0
"""Bounded retry for a deterministic per-item failure (§7.9; D8, D10; the owner's rulings on the 2b-4b M3 design):
counted by the pass's own kind, apart from the item's own attempts; 1, 2, 4, 8, 16, 30 minutes between tries; held at
the 7th, alerting once, for an operator's release only; cleared by a success. Neither the database failing nor an
uncertain Temporal answer counts."""

import uuid
from typing import Any

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import failures
from tests.core.claims.test_service import a_tenant, statements


@pytest.mark.parametrize(
    ("error", "counts"),
    [
        (RuntimeError("a bug"), True),
        (KeyError("a bug"), True),
        (RPCError("refused", RPCStatusCode.INVALID_ARGUMENT, b""), True),
        (RPCError("refused", RPCStatusCode.PERMISSION_DENIED, b""), True),
        (RPCError("down", RPCStatusCode.UNAVAILABLE, b""), False),
        (RPCError("slow", RPCStatusCode.DEADLINE_EXCEEDED, b""), False),
        (RPCError("busy", RPCStatusCode.RESOURCE_EXHAUSTED, b""), False),
        (TimeoutError(), False),
        (ConnectionRefusedError(), False),  # the database (or anything) not answering
    ],
    ids=lambda v: type(v).__name__ if isinstance(v, BaseException) else str(v),
)
def test_only_what_isnt_an_outage_or_an_uncertain_answer_counts(error: BaseException, counts: bool) -> None:
    assert failures.counted(error) is counts


async def state(owner: Any, tenant: uuid.UUID, kind: str, item: uuid.UUID) -> tuple[Any, ...] | None:
    """The item's count for `kind`: its errors, whether it's held, its delay to the next try (seconds), its error."""
    async with owner() as s:
        found = await s.execute(
            text(
                "select errors, held_at is not null, round(extract(epoch from due_at - statement_timestamp())), "
                "last_error from work_failures where tenant_id = :t and kind = :k and item_id = :i"
            ),
            {"t": tenant, "k": kind, "i": item},
        )
        row = found.first()
    return tuple(row) if row is not None else None


async def test_seven_consecutive_failures_hold_an_item_for_its_kind_alerting_once(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    tenant, item = await a_tenant(owner_sessionmaker), uuid.uuid4()
    seen = []
    with structlog.testing.capture_logs() as logs:
        for _ in range(8):
            await failures.failed(dispatch_sessionmaker, tenant, failures.DISPATCH, item, RuntimeError("a bug"))
            seen.append(await state(owner_sessionmaker, tenant, failures.DISPATCH, item))
    delays = [round(d.total_seconds()) for d in failures.DELAYS]
    assert [(e, h) for e, h, _, _ in seen] == [(n, n >= 7) for n in range(1, 9)]
    assert [d for _, _, d, _ in seen[:6]] == [60, *delays[1:]]  # 1, 2, 4, 8, 16, 30 minutes
    assert {err for *_, err in seen} == {"RuntimeError"}  # its type, never its text
    assert [e["event"] for e in logs if e["event"].endswith("_held")] == ["dispatch_held"]


async def test_a_kinds_failures_never_touch_another_kinds_and_a_success_clears_only_its_own(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    """The owner's ruling: dispatch, reconciliation and a cancel may concern one request; a reconcile failure is
    counted by its phase, so a hold from one phase never suppresses the next."""
    tenant, item = await a_tenant(owner_sessionmaker), uuid.uuid4()
    for kind in (failures.CANCEL, failures.RECONCILE["starting"]):
        await failures.failed(dispatch_sessionmaker, tenant, kind, item, RuntimeError("a bug"))
    assert await state(owner_sessionmaker, tenant, failures.DISPATCH, item) is None
    assert await state(owner_sessionmaker, tenant, failures.RECONCILE["open"], item) is None
    await failures.cleared(dispatch_sessionmaker, list(failures.RECONCILE.values()), [(tenant, item)])
    assert await state(owner_sessionmaker, tenant, failures.RECONCILE["starting"], item) is None
    assert (await state(owner_sessionmaker, tenant, failures.CANCEL, item))[0] == 1  # type: ignore[index]


async def test_a_pass_with_no_success_clears_nothing_and_asks_nothing(dispatch_sessionmaker) -> None:
    """Most passes' items never failed: clearing is one statement for the pass, and none for a pass with nothing."""
    with statements(dispatch_sessionmaker) as seen:
        await failures.cleared(dispatch_sessionmaker, [failures.DISPATCH], [])
    assert seen == []


async def test_an_outage_or_an_uncertain_answer_is_never_counted(owner_sessionmaker, dispatch_sessionmaker) -> None:
    tenant, item = await a_tenant(owner_sessionmaker), uuid.uuid4()
    for error in (ConnectionRefusedError(), RPCError("down", RPCStatusCode.UNAVAILABLE, b""), TimeoutError()):
        await failures.failed(dispatch_sessionmaker, tenant, failures.CANCEL, item, error)
    assert await state(owner_sessionmaker, tenant, failures.CANCEL, item) is None


async def test_a_failure_that_cant_be_recorded_is_logged_by_its_type_never_raised(dispatch_sessionmaker) -> None:
    """Recording runs in the pass's handler for the item: a refusal there (here, no such tenant; an erased tenant's
    fence alike), or the database gone, mustn't end the pass. Its log names the error's type, never its text."""
    gone = async_sessionmaker(create_async_engine("postgresql+asyncpg://nobody@127.0.0.1:9/none"))
    with structlog.testing.capture_logs() as logs:
        await failures.failed(dispatch_sessionmaker, uuid.uuid4(), failures.DISPATCH, uuid.uuid4(), KeyError("x"))
        await failures.failed(gone, uuid.uuid4(), failures.DISPATCH, uuid.uuid4(), KeyError("x"))
        await failures.cleared(gone, [failures.DISPATCH], [(uuid.uuid4(), uuid.uuid4())])
    assert [(e["event"], e["error"]) for e in logs] == [
        ("failure_unrecorded", "IntegrityError"), ("failure_unrecorded", "ConnectionRefusedError"),
        ("failures_uncleared", "ConnectionRefusedError"),
    ]  # fmt: skip
