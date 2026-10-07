# SPDX-License-Identifier: Apache-2.0
"""How often the dispatcher's leader describes run executions' evidence again (the final review's I3). It takes 50
due rows a pass, oldest due first, on the cycle that dispatches, so a row it has just described must come back later,
never at once: a read execution Temporal still keeps is next described no sooner than five minutes on (its close plus
the retention can be long past), and one Temporal never showed backs off, its wait doubling up to a day. However many
rows are due, every one is described within N/50 passes, rounded up, the earliest due first."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from temporalio.client import WorkflowExecutionStatus

from dewpoint.apps.dispatcher import evidence
from tests.support.workflows import seed_workflow

RETENTION = timedelta(days=1)


class Closed:
    """A closed execution as Temporal describes it."""

    status = WorkflowExecutionStatus.COMPLETED
    close_time = datetime.now(UTC) - timedelta(days=10)
    run_id = "closed-run"


async def _rows(owner: Any, tenant: uuid.UUID, n: int, *, read: bool, checked_ago: timedelta | None = None) -> None:
    async with owner() as s, s.begin():
        for _ in range(n):
            await s.execute(text(
                "insert into execution_evidence (tenant_id, workflow_id, run_id, started_at, seen_at, checked_at, "
                "read_at, next_check_at) values (:t, :w, :r, now() - interval '20 days', :seen, :checked, :read, now())"
            ), {"t": tenant, "w": f"t:{tenant}:run:{uuid.uuid4()}", "r": "a-run" if read else None,
                "seen": datetime.now(UTC) if read else None,
                "checked": None if checked_ago is None else datetime.now(UTC) - checked_ago,
                "read": datetime.now(UTC) if read else None})  # fmt: skip


async def test_more_due_rows_than_a_pass_takes_are_all_described_within_a_few_passes(
    owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """Executions Temporal still keeps, long closed: the old schedule (their close plus the retention) put each back in
    the past, so the same 50 came due on every pass and the rest never did."""
    described: list[str] = []

    async def kept(client: object, workflow_id: str, run_id: str | None) -> Closed:
        described.append(workflow_id)
        return Closed()

    monkeypatch.setattr(evidence, "_described", kept)
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    await _rows(owner_sessionmaker, tenant, 60, read=True)
    for _ in range(2):
        await evidence.check_evidence(dispatch_sessionmaker, None, retention=RETENTION)  # type: ignore[arg-type]
    async with owner_sessionmaker() as s:
        due = (await s.execute(text("select count(*) from execution_evidence where tenant_id = :t "
                                    "and next_check_at <= now()"), {"t": tenant})).scalar_one()  # fmt: skip
    assert (len(described), len(set(described)), due) == (60, 60, 0)


async def test_an_execution_temporal_never_showed_is_described_less_and_less_often_up_to_a_day(
    owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    async def unshown(client: object, workflow_id: str, run_id: str | None) -> None:
        return None

    monkeypatch.setattr(evidence, "_described", unshown)
    waits = []
    for ago in (None, timedelta(hours=1), timedelta(hours=20)):  # first asked, asked an hour ago, twenty hours ago
        tenant, _, _ = await seed_workflow(owner_sessionmaker)
        await _rows(owner_sessionmaker, tenant, 1, read=False, checked_ago=ago)
        await evidence.check_evidence(dispatch_sessionmaker, None, retention=RETENTION)  # type: ignore[arg-type]
        async with owner_sessionmaker() as s:
            wait = (await s.execute(text("select next_check_at - checked_at from execution_evidence "
                                         "where tenant_id = :t"), {"t": tenant})).scalar_one()  # fmt: skip
        waits.append(round(wait.total_seconds() / 60))
    assert waits == [5, 120, 24 * 60]  # minutes: five at first, then twice the last gap, never over a day
