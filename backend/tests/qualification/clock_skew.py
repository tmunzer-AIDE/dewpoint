# SPDX-License-Identifier: Apache-2.0
"""The difference between Temporal's clock and the database's on the target (ruling 5; task 15's `clock_skew_max`),
through paired readings: the database's `statement_timestamp()` read just before and just after Temporal stamps an
execution (its start, then its close by termination), so each Temporal time must fall inside that window but for the
skew. A reading outside it shows at least that much skew.

It proposes the largest skew observed, plus a margin, for the qualification interval's `clock_skew_max`. Nothing uses
that value unless the qualification records it in `target_qualification_intervals`; with none recorded, nothing
qualifies `retained_out`. The executions it makes (`qualification:clock:<id>`, a task queue no worker serves) are
terminated and deleted: run it with a Temporal identity of the qualification's (`DEWPOINT_TEMPORAL_*`) allowed to start
and delete `qualification:clock:*`, never the deployment's own. A round that fails is recorded, and the run fails.

    DEWPOINT_QUALIFICATION_APPROVED=<id> DEWPOINT_QUALIFICATION_DB_PASSWORD=... DEWPOINT_TEMPORAL_ADDRESS=... \\
    python -m tests.qualification.clock_skew --dsn '<a login's verify-full DSN>' --rounds 20 --margin-ms 500 \\
      --out clock_skew.jsonl"""

import argparse
import asyncio
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from temporalio.api.common.v1 import WorkflowExecution
from temporalio.api.workflowservice.v1 import DeleteWorkflowExecutionRequest

from dewpoint.apps.cli import recovery
from dewpoint.core import temporal_connect
from dewpoint.core.config import get_settings
from tests.qualification.approval import Record, approved, secret

DESCRIPTION = "Temporal's clock against the database's, through paired readings: a proposed clock_skew_max."
QUEUE = "dewpoint-qualification-clock"  # no worker serves it


def bound(db_before: datetime, temporal_at: datetime, db_after: datetime) -> timedelta:
    """The largest skew one reading is consistent with: Temporal stamped `temporal_at` at some database time within
    [db_before, db_after], so its skew lies in [temporal_at - db_after, temporal_at - db_before], and a maximum rests
    on the larger magnitude, the window's width included (never the smallest skew, which reads 0 inside it)."""
    return max(abs(temporal_at - db_before), abs(temporal_at - db_after))


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1: nothing measured qualifies nothing")
    return value


def _non_negative(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more: a negative margin would propose less than measured")
    return value


def proposed(observed: Sequence[timedelta], *, margin: timedelta) -> timedelta:
    """The largest skew observed, plus the margin."""
    return max(observed) + margin


async def _measured(args: argparse.Namespace, record: Record) -> list[timedelta]:
    target = recovery.server(args.dsn, user=recovery.ADMINISTRATOR)
    db = await recovery.connect(target, secret("DEWPOINT_QUALIFICATION_DB_PASSWORD"))
    client = await temporal_connect.connect(get_settings(), "production")

    async def now() -> Any:
        return await db.fetchval("select statement_timestamp()")

    observed: list[timedelta] = []
    try:
        for n in range(args.rounds):
            workflow_id = f"qualification:clock:{uuid.uuid4()}"
            try:
                observed += await _round(client, now, workflow_id, n, record)
            except Exception as e:  # recorded, never passed over: a round that failed measured nothing
                record.check(False, f"round {n + 1}: measured", error=type(e).__name__)
    finally:
        await db.close()
    return observed


async def _round(client: Any, now: Any, workflow_id: str, n: int, record: Record) -> list[timedelta]:
    """One round's two readings: Temporal's start and close times, each between two of the database's."""
    before = await now()
    handle = await client.start_workflow("QualificationClock", id=workflow_id, task_queue=QUEUE)
    middle = await now()
    await handle.terminate(reason="qualification: clock skew")
    after = await now()
    described = await handle.describe()
    started, closed = described.start_time, described.close_time
    skews = [bound(before, started, middle), bound(middle, closed, after)] if closed else []
    record.check(bool(skews), f"round {n + 1}: both Temporal times read", started=started, closed=closed,
                 db=(before, middle, after), skews=[s.total_seconds() for s in skews])  # fmt: skip
    await client.workflow_service.delete_workflow_execution(DeleteWorkflowExecutionRequest(
        namespace=client.namespace, workflow_execution=WorkflowExecution(workflow_id=workflow_id),
    ))  # fmt: skip  # nothing of it kept
    return skews


def main() -> int:
    approval = approved()
    parser = argparse.ArgumentParser(prog="python -m tests.qualification.clock_skew", description=DESCRIPTION)
    parser.add_argument("--dsn", required=True, help="a database login's, verify-full (its clock is the database's)")
    parser.add_argument("--rounds", type=_positive, required=True)
    parser.add_argument("--margin-ms", type=_non_negative, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    record = Record(args.out, "clock_skew", approval)
    observed = asyncio.run(_measured(args, record))
    record.check(len(observed) == 2 * args.rounds, "every round measured both Temporal times", measured=len(observed))
    if observed:
        skew = proposed(observed, margin=timedelta(milliseconds=args.margin_ms))
        record.write(proposed_clock_skew_max_s=skew.total_seconds(), observed_max_s=max(observed).total_seconds(),
                     note="recorded in target_qualification_intervals only by the qualification itself")  # fmt: skip
    return record.finished()


if __name__ == "__main__":
    raise SystemExit(main())
