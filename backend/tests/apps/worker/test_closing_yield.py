# SPDX-License-Identifier: Apache-2.0
"""#16's extra task failure: the 1 ms timer that ends a workflow task (`_yield_point`, and `_drive` when a take is cut
short) is shared by an execution's units and raced, so a unit's result can win and the execution carry on, and close,
with the timer still pending. Should it fire while the closing task is in flight, Temporal refuses the close
(UNHANDLED_COMMAND, by the worker) and the run closes in a task after. An execution cancels it as it closes; a history
recorded before that (no patch marker) replays as it ran.

Here the timer is stretched to a minute (`YIELD_TIMER_S`), so it's still pending when the run closes: on the
time-skipping server time doesn't skip while an activity runs, and the run's units keep it from waiting on the timer
alone."""

from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer

from dewpoint.engine.cel import route
from dewpoint.engine.runtime import execution
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.apps.worker.harness import MemoryStore, start, workers
from tests.support.graphs import G
from tests.support.keys import FIXTURE_CONVERTER

STRETCHED = 60.0
STEPS = 12


def fan_out() -> G:
    g = G()
    for n in range(STEPS):
        g.node(f"x{n}", "testkit.echo@1", {"value": n})
    return g


def timers(events: list[Any]) -> tuple[set[int], set[int], set[int]]:
    """The stretched timers started, fired and cancelled, each by the event that started it."""
    started = {
        e.event_id
        for e in events
        if e.event_type == EventType.EVENT_TYPE_TIMER_STARTED
        and e.timer_started_event_attributes.start_to_fire_timeout.ToTimedelta().total_seconds() == STRETCHED
    }
    fired = {
        e.timer_fired_event_attributes.started_event_id for e in events if e.HasField("timer_fired_event_attributes")
    }
    cancelled = {
        e.timer_canceled_event_attributes.started_event_id
        for e in events
        if e.HasField("timer_canceled_event_attributes")
    }
    return started, fired & started, cancelled & started


async def stretched_run(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> list[WorkflowHistory]:
    """Takes cut short (a few steps each) and early drains: a drain takes nothing new, so the steps still queued keep
    the timer started while the run waits for what's outstanding, and it continues as new once that settles. Every
    execution of the chain, first to last."""
    monkeypatch.setattr(execution, "TAKE_WEIGHT", route.YIELD_STRUCTURE // 4)  # takes of four steps a task
    monkeypatch.setattr(execution, "YIELD_TIMER_S", STRETCHED)
    store = MemoryStore()
    async with workers(env.client, store):
        handle = await start(env.client, store, fan_out(), checkpoint_events=20, drain_events=20)
        assert (await handle.result()).status == "succeeded"
        histories, run_id = [], handle.first_execution_run_id
        while run_id:
            history = await env.client.get_workflow_handle(handle.id, run_id=run_id).fetch_history()
            histories.append(history)
            last = history.events[-1]
            run_id = (
                last.workflow_execution_continued_as_new_event_attributes.new_execution_run_id
                if last.HasField("workflow_execution_continued_as_new_event_attributes")
                else None
            )
    return histories


async def test_a_yield_timer_still_pending_as_an_execution_closes_is_cancelled_with_its_close(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    histories = await stretched_run(env, monkeypatch)
    assert len(histories) > 1, "the run never continued as new"
    pending, cancelled = [], []
    for n, history in enumerate(histories):
        events = list(history.events)
        started, fired, cut = timers(events)
        pending += [(n, e) for e in sorted(started - fired - cut)]
        cancelled += [(n, e) for e in sorted(cut)]
        assert not [e for e in events if e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED]
    assert pending == []  # (execution, the event that started it): none left pending at its close
    assert cancelled, "no execution closed with the timer pending: the case wasn't reached"
    replayer = Replayer(workflows=[RunGraph, LoopBatch], data_converter=FIXTURE_CONVERTER)
    for history in histories:  # the patch's marker and the cancel replay as they ran
        await replayer.replay_workflow(history)


async def test_a_history_recorded_without_the_cancel_replays_as_it_ran(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """Recorded as the build before ran (no cancel, no marker: an execution closed with the timer pending), the chain
    replays on this one; a cancel without the patch's gate would not (a command the history doesn't have)."""
    closing = execution.Execution._closing
    monkeypatch.setattr(execution.Execution, "_closing", lambda self: None)
    histories = await stretched_run(env, monkeypatch)
    assert any(timers(list(h.events))[0] - timers(list(h.events))[1] for h in histories), "nothing left pending"
    monkeypatch.setattr(execution.Execution, "_closing", closing)
    replayer = Replayer(workflows=[RunGraph, LoopBatch], data_converter=FIXTURE_CONVERTER)
    for history in histories:
        await replayer.replay_workflow(history)

    def ungated(self: execution.Execution) -> None:
        if self._yield_timer is not None and not self._yield_timer.done():
            self._yield_timer.cancel()

    monkeypatch.setattr(execution.Execution, "_closing", ungated)
    pending = [h for h in histories if timers(list(h.events))[0] - timers(list(h.events))[1]]
    with pytest.raises(Exception, match="[Nn]ondeterminism"):
        await replayer.replay_workflow(pending[0])
