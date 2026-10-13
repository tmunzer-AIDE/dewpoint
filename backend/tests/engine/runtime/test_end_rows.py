# SPDX-License-Identifier: Apache-2.0
"""A run's end rows, as projections send them (B4b; the simulation design §9): however a projection's byte cut
divides what waits, none carries more than ENDS_PER_PROJECTION end rows, and each call makes at most that many. Counted
in rows, on the execution's own queue, without a workflow."""

import collections
import uuid
from types import SimpleNamespace

from dewpoint.engine.runtime import scheduler as live_state
from dewpoint.engine.runtime.activities import StepRow
from dewpoint.engine.runtime.execution import ENDS_PER_PROJECTION, Execution
from dewpoint.engine.runtime.scheduler import Instance

NOW = "2026-10-13T00:00:00+00:00"


def execution() -> Execution:
    """An execution's row queue alone: `_queue_end` needs only the step an instance is of."""
    ex = Execution.__new__(Execution)
    ex.run_id = str(uuid.UUID(int=1))
    ex.sched = SimpleNamespace(step=lambda inst: SimpleNamespace(id=inst.step, key="s", control=False))
    ex._rows, ex._ends_pending = {}, collections.deque()
    ex._started, ex._cel_modes, ex._finished, ex._attempted, ex._end_keys = {}, {}, set(), set(), set()
    return ex


def test_a_byte_cut_projection_never_sends_more_than_its_end_rows_limit() -> None:
    ex = execution()
    for n in range(100):  # rows waiting already, each with a preview near its 8 KiB bound
        ex._queue(
            StepRow(ex.run_id, str(uuid.UUID(int=10_000 + n)), "big", "", 1, "succeeded", output_preview="x" * 4000)
        )
    ex._ends_pending.extend((Instance((("l", n),), uuid.UUID(int=2)), live_state.UNSTARTED, NOW) for n in range(2_000))
    per_projection: list[int] = []
    while ex._rows_ready():
        per_projection.append(sum(1 for r in ex._take_rows() if r.status == "not_started"))
    assert sum(per_projection) == 2_000 and not ex._rows and not ex._ends_pending
    assert max(per_projection) <= ENDS_PER_PROJECTION == 500
