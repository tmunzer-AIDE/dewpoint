# SPDX-License-Identifier: Apache-2.0
"""B4b (the simulation design §3): every instance of every opened scope ends with a row. A branch not taken is
`skipped`; work discarded before it began is `not_started`, with no start; work stopped once it began is `cancelled`;
a retry stopped in its backoff is `not_started` at the attempt it waited for; a control step that waits on something
says `running` first; a control step that finished as its run ended keeps its outcome; an `if`'s port and a
`set_variables`'s assignments are its `effect_preview`."""

import asyncio
import dataclasses
from typing import Any

import pytest
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.runtime import scheduler
from dewpoint.engine.runtime.activities import ProjectInput
from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, run_id_of, start, workers
from tests.support.graphs import G, cel
from tests.support.plugins.testkit import Slow

ECHO, SLOW, FAIL_N = "testkit.echo@1", "testkit.slow@1", "testkit.fail_n@1"
IF, LOOP, SET, DELAY, STOP = "flow.if@1", "flow.loop@1", "flow.set_variables@1", "flow.delay@1", "flow.stop@1"
FAIL, FILTER = "flow.fail@1", "flow.filter@1"
SAID_TIMEOUT_S = 10  # real time for a projection to land, far more than one takes


def graph() -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}}
    return g


def ended(store: MemoryStore, run_id: str) -> dict[tuple[str, str, int], tuple[str, bool]]:
    """Each row's (status, whether it has a start), by (step, iteration, attempt)."""
    return {(r.node_key, r.iteration_key, r.attempt): (r.status, r.started_at is not None) for r in store.steps(run_id)}


@dataclasses.dataclass
class Seen(MemoryStore):
    """Every (step, status) a projection carried, in order: what a run said while it ran."""

    seen: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    said: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    async def project(self, data: ProjectInput) -> None:
        self.seen += [(r.node_key, r.status) for r in data.steps]
        if ("d", "running") in self.seen:
            self.said.set()
        await super().project(data)


async def test_the_deadline_cancels_running_work_and_ends_waiting_work_not_started(
    own_env: WorkflowEnvironment,
) -> None:
    """On a test server of its own: the run ends while `a`'s activity runs, and a shared server would stop skipping
    time."""
    store = MemoryStore()
    g = graph().node("a", SLOW, {"seconds": 60}).node("b", ECHO, {"value": 1}).edge("a", "b")
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {}, max_run_duration_s=5)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.status == "deadline_exceeded"
    assert ended(store, run_id_of(handle)) == {("a", "", 1): ("cancelled", True), ("b", "", 1): ("not_started", False)}


async def test_a_retry_stopped_in_its_backoff_is_not_started_at_the_attempt_it_waited_for(
    env: WorkflowEnvironment,
) -> None:
    """D-a1: attempt 1 keeps its failure; attempt 2 never began (the backoff is 1 s, the deadline half of it)."""
    store = MemoryStore()
    g = graph().node("f", FAIL_N, {"failures": 1})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, max_run_duration_s=0.5)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.status == "deadline_exceeded"
    rows = {r.attempt: r for r in store.steps(run_id_of(handle))}
    assert (rows[1].status, rows[1].error_code) == ("failed", "testkit.transient")
    assert (rows[2].status, rows[2].started_at, rows[2].input_preview) == ("not_started", None, None)


async def test_a_stop_cancels_a_sleeping_timer_that_said_it_was_running(env: WorkflowEnvironment) -> None:
    """D-a2: a control step that waits on something says `running` first; stopped, it's `cancelled` with its start."""
    store = Seen()
    g = graph().node("d", DELAY, {"duration_s": 3600}).node("s", SLOW, {"seconds": 1}).node("stop", STOP)
    g.edge("s", "stop")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.status == "succeeded"  # a stop ends the run as succeeded
    assert ("d", "running") in store.seen
    assert ended(store, run_id_of(handle))[("d", "", 1)] == ("cancelled", True)


async def test_a_timer_alone_in_its_run_says_it_is_running_while_it_sleeps(env: WorkflowEnvironment) -> None:
    """D-a2 with nothing beside the timer to wake the run: its `running` row is projected as it falls asleep, not
    when it wakes. The test waits in real time, never for the result, so the server skips no time meanwhile."""
    store = Seen()
    g = graph().node("d", DELAY, {"duration_s": 3600})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        try:
            await asyncio.wait_for(store.said.wait(), SAID_TIMEOUT_S)
        finally:
            await handle.cancel()
            with pytest.raises(WorkflowFailureError):
                await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert ended(store, run_id_of(handle))[("d", "", 1)] == ("cancelled", True)


async def test_a_plugin_step_alone_in_its_run_says_it_is_running_while_its_activity_runs(
    own_env: WorkflowEnvironment,
) -> None:
    """Its attempt's `running` row is projected as the activity starts, not when it ends. On a test server of its
    own: the run is cancelled while the activity runs."""
    store = Seen()
    g = graph().node("d", SLOW, {"seconds": 60})
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {})
        try:
            await asyncio.wait_for(store.said.wait(), SAID_TIMEOUT_S)
        finally:
            await handle.cancel()
            with pytest.raises(WorkflowFailureError):
                await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert ended(store, run_id_of(handle))[("d", "", 1)] == ("cancelled", True)


async def test_a_failed_iteration_ends_its_own_steps_and_leaves_the_other_iterations(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("l", LOOP, {"items": [0, 1]}, on_error="continue")
    g.nodes[0]["config"]["on_item_error"] = "continue"
    g.node("x", IF, {"condition": cel("item == 0")}).node("f", FAIL_N, {"failures": 10}).node("e", ECHO, {"value": 1})
    g.node("after_f", ECHO, {"value": 2})
    g.edge("l", "x", "body").edge("x", "f", "true").edge("x", "e", "false").edge("f", "after_f")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.status == "succeeded"
    rows = ended(store, run_id_of(handle))
    finals = {(k, it): rows[(k, it, max(a for kk, ii, a in rows if (kk, ii) == (k, it)))][0] for k, it, _ in rows}
    assert finals == {
        ("l", ""): "succeeded",
        ("x", "l:0"): "succeeded", ("f", "l:0"): "failed", ("e", "l:0"): "skipped", ("after_f", "l:0"): "not_started",
        ("x", "l:1"): "succeeded", ("f", "l:1"): "skipped", ("e", "l:1"): "succeeded", ("after_f", "l:1"): "skipped",
    }  # fmt: skip


async def test_the_port_an_if_took_and_what_set_variables_assigned_are_recorded(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph()
    g.settings["vars_schema"] = {"type": "object", "properties": {"n": {"type": "integer", "default": 0}}}
    g.node("v", SET, {"assignments": {"n": 3}}).node("c", IF, {"condition": cel("vars.n > 2")})
    g.node("yes", ECHO, {"value": 1}).edge("v", "c").edge("c", "yes", "true")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    rows = {r.node_key: r for r in store.steps(run_id_of(handle))}
    assert rows["v"].effect_preview == {"assignments": {"n": 3}}
    assert rows["c"].effect_preview == {"port": "true"}
    assert rows["yes"].effect_preview is None


async def test_a_control_step_that_finished_as_the_run_ended_keeps_its_outcome(env: WorkflowEnvironment) -> None:
    """D-a3: `stop` and `v` start together and finish in the same activation; `stop` is applied first and ends the
    run, and `v`'s outcome, known by then, is its row."""
    store = MemoryStore()
    g = graph()
    g.settings["vars_schema"] = {"type": "object", "properties": {"n": {"type": "integer", "default": 0}}}
    g.node("stop", STOP).node("v", SET, {"assignments": {"n": 1}})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    rows: dict[str, Any] = {r.node_key: r for r in store.steps(run_id_of(handle))}
    assert (rows["stop"].status, rows["v"].status) == ("succeeded", "succeeded")
    assert rows["v"].effect_preview == {"assignments": {"n": 1}}


async def test_a_control_step_that_finished_as_the_deadline_passed_keeps_its_outcome(
    dev_env: WorkflowEnvironment,
) -> None:
    """D-a3 in the deadline's order: `d` sleeps as long as the run may last, and its timer and the deadline's fire in
    one workflow task; `d`'s row says what it did, never `cancelled`. Forced, as the server's timing won't: the run's
    build stops once both timers are started and serves again once both have fired, so its next task carries both. On
    the dev server: the time-skipping one stalls on the two (the env fixture says where it does)."""
    from temporalio.api.enums.v1 import EventType

    from tests.apps.worker.test_real_server import serving

    async def history(handle: Any, kind: int, count: int) -> list[int]:
        for _ in range(200):  # in real time: the timers are 5 s
            kinds = [e.event_type for e in (await handle.fetch_history()).events]
            if kinds.count(kind) >= count:
                return kinds
            await asyncio.sleep(0.1)
        raise AssertionError(f"fewer than {count} events of type {kind}")

    store = MemoryStore()
    g = graph().node("d", DELAY, {"duration_s": 5})
    async with serving(dev_env.client, store) as this:
        handle = await start(dev_env.client, store, g, {}, max_run_duration_s=5)
        await history(handle, EventType.EVENT_TYPE_TIMER_STARTED, 2)
    await history(handle, EventType.EVENT_TYPE_TIMER_FIRED, 2)  # no worker polls: both wait for the same task
    async with serving(dev_env.client, store, again=this):
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
        kinds = [e.event_type for e in (await handle.fetch_history()).events]
    assert result.status == "deadline_exceeded"
    first, second = [i for i, k in enumerate(kinds) if k == EventType.EVENT_TYPE_TIMER_FIRED]
    assert EventType.EVENT_TYPE_WORKFLOW_TASK_STARTED not in kinds[first:second], "the timers fired in different tasks"
    [row] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "d"]
    assert (row.status, row.started_at is not None) == ("succeeded", True)


async def test_a_simulated_timer_that_finished_as_the_run_stopped_says_it_wasnt_waited(
    env: WorkflowEnvironment,
) -> None:
    """D-a3 for a simulated timer: its row is the one it would have had otherwise, `simulated`, with its resolved
    duration as its input (the simulation design §4.2)."""
    store = MemoryStore()
    g = graph().node("stop", STOP).node("wait", DELAY, {"duration_s": 3600})  # `stop` is applied first, as it ranks
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, mode="simulate")
        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    [row] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "wait"]
    assert (row.status, row.outcome, row.input_preview) == ("succeeded", "simulated", {"duration_s": 3600})


BIG = ["a" * 2_000, "b" * 2_000]  # a filter keeping both passes a 3,000-byte budget: claimed before it merges


@pytest.mark.parametrize("name", ["f", "x"])
async def test_a_control_step_past_the_budget_that_finished_as_the_run_ended_keeps_its_outcome(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """D-a3 past the live-state budget (engine 2b spec §5.3): the filter and `stop` finish in the same activation. `f`
    ranks before `stop`, so its result waits to be claimed when the run ends; `x` ranks after it, so the run has ended
    when its result comes. Either way its row is what it did."""
    monkeypatch.setattr(scheduler, "LIVE_BUDGET", 3_000)
    store = MemoryStore()
    g = graph().node("stop", STOP).node(name, FILTER, {"items": BIG, "predicate": cel("true")})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    [row] = [r for r in store.steps(run_id_of(handle)) if r.node_key == name]
    assert (row.status, row.outcome, row.output_preview is not None) == ("succeeded", None, True)


@dataclasses.dataclass
class HeldSpills(MemoryStore):
    """A spill is written only once `release` is set: a result being claimed while the run ends."""

    release: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    held: int = 0

    async def write(
        self, tenant_id: str, claims: Any, *, kind: str, step_id: str | None, iteration_key: str | None
    ) -> None:
        if kind == "spill":
            self.held += 1
            await self.release.wait()
        await super().write(tenant_id, claims, kind=kind, step_id=step_id, iteration_key=iteration_key)


async def test_a_control_step_whose_result_was_being_claimed_as_the_run_ended_keeps_its_outcome(
    own_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-a3 while a claim is written: `f`'s result passes the budget, so it's claimed before it merges; `stop` ends the
    run a second later, with the claim still being written. `f`'s row is what it did. On a test server of its own: the
    claim's activity never completes against the closed run, and a shared server would stop skipping time."""
    monkeypatch.setattr(scheduler, "LIVE_BUDGET", 3_000)
    store = HeldSpills()
    g = graph().node("f", FILTER, {"items": BIG, "predicate": cel("true")}).node("s", SLOW, {"seconds": 1})
    g.node("stop", STOP).edge("s", "stop")
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
        store.release.set()
    assert result.status == "succeeded"
    assert store.held == 1  # the claim was under way when the run ended
    [row] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "f"]
    assert (row.status, row.outcome, row.output_preview is not None) == ("succeeded", None, True)


async def test_a_control_step_whose_result_was_being_claimed_as_its_iteration_failed_is_rowed_once(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-a3 in a scope: `f`'s result is being claimed when `z` fails its iteration, so `f`'s row says what it did; the
    claim lands later, while the run goes on, and merges nothing, nor rows `f` again."""
    monkeypatch.setattr(scheduler, "LIVE_BUDGET", 3_000)
    store = HeldSpills()
    g = graph().node("l", LOOP, {"items": [0], "on_item_error": "continue"}, on_error="continue")
    g.node("f", FILTER, {"items": BIG, "predicate": cel("true")}).node(
        "z", "flow.transform@1", {"fields": {"r": cel("1 / item")}}
    )
    g.node("s", SLOW, {"seconds": 3}).edge("l", "f", "body").edge("l", "z", "body").edge("l", "s", "done")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        run_id = run_id_of(handle)
        for _ in range(100):  # until `f`'s row is written: then the claim lands
            if any(r.node_key == "f" and r.status != "running" for r in store.steps(run_id)):
                break
            await asyncio.sleep(0.05)
        store.release.set()
        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert store.held == 1  # the claim was under way when the iteration failed
    rows = {r.node_key: r for r in store.steps(run_id)}
    assert (rows["z"].status, rows["f"].status, rows["f"].output_preview is not None) == ("failed", "succeeded", True)
    assert store.conflicts == []


async def test_a_cancel_ends_started_work_cancelled_and_queued_work_not_started(own_env: WorkflowEnvironment) -> None:
    """101 steps ready at once: the in-flight cap starts 100 and queues one. A cancel stops the 100 that began
    (`cancelled`, with their start); the one queued never began (`not_started`, no start). About 30 s: the run's last
    projection waits for one of the worker's 100 activity slots, which the steps hold until a cancel reaches them with
    the next heartbeat the SDK sends (no step sets a heartbeat timeout). The run ends once one step gives its slot back,
    and others may still be running (one whose first heartbeat came after the cancel hears of it at once): on a test
    server of its own, as a shared one would stop skipping time."""
    store = MemoryStore()
    g = graph()
    for n in range(101):
        g.node(f"s{n}", SLOW, {"seconds": 120})
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {})
        run_id = run_id_of(handle)
        for _ in range(600):  # until the cap's 100 have begun: each beats once a second
            if sum(1 for run, _ in Slow.beats if run == run_id) >= 100:
                break
            await asyncio.sleep(0.05)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert store.runs[run_id].status == "cancelled"
    rows = ended(store, run_id)
    assert sorted(rows.values()).count(("cancelled", True)) == 100
    assert [v for v in rows.values() if v != ("cancelled", True)] == [("not_started", False)]


async def test_a_loop_open_across_a_continue_as_new_ends_cancelled_with_its_first_start(
    env: WorkflowEnvironment,
) -> None:
    """A loop whose iterations still sleep when the run continues as new began in the first execution: a cancel in
    the continued one ends it `cancelled`, with the start the first one recorded, never `not_started`."""
    from tests.apps.worker.test_run_graph_continue import chain

    store = MemoryStore()
    g = graph()
    g.node("l", LOOP, {"items": list(range(10)), "concurrency": 10}).node("d", DELAY, {"duration_s": 3600})
    g.edge("l", "d", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, drain_events=15)
        for _ in range(200):
            if len(await chain(env.client, handle.id, handle.first_execution_run_id or "")) >= 2:
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("it never continued as new")
        first = [r.started_at for r in store.steps(run_id_of(handle)) if r.node_key == "l"]
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    [loop] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "l"]
    assert (loop.status, loop.started_at) == ("cancelled", first[0])
    assert {r.status for r in store.steps(run_id_of(handle)) if r.node_key == "d"} == {"cancelled"}


async def test_inside_a_batch_every_opened_iteration_ends_each_of_its_steps(env: WorkflowEnvironment) -> None:
    """A loop of 150 items runs its iterations in batches (child runs), which row their ends as the run does: item
    130's `if` takes `true` and fails the run; the branch it didn't take is `skipped`; every step of every iteration
    that opened has its final row, and no iteration that never opened has any."""
    store = MemoryStore()
    g = graph()
    g.node("l", LOOP, {"items": list(range(150))})
    g.node("i", IF, {"condition": cel("item == 130")}).node("f", FAIL, {"message": "item 130"}).node("e", ECHO)
    g.edge("l", "i", "body").edge("i", "f", "true").edge("i", "e", "false")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert (result.status, result.error["code"]) == ("failed", "workflow_failed")
    rows = ended(store, run_id_of(handle))
    assert rows[("e", "l:130", 1)] == ("skipped", False) and rows[("f", "l:130", 1)][0] == "failed"
    opened = {key for (_, key, _) in rows if key.startswith("l:")}
    assert "l:130" in opened and all({n for (n, k, _) in rows if k == key} == {"i", "f", "e"} for key in opened)
    assert all(status != "running" for status, _ in rows.values())


# --- flow timers in a simulation (the simulation design §4.2) ------------------------------------------------------


def timers(history: Any) -> list[float]:
    """Each timer the run started: its duration, in seconds."""
    from temporalio.api.enums.v1 import EventType

    return [
        e.timer_started_event_attributes.start_to_fire_timeout.ToTimedelta().total_seconds()
        for e in history.events
        if e.event_type == EventType.EVENT_TYPE_TIMER_STARTED
    ]


async def test_a_simulated_delay_is_resolved_but_not_waited(env: WorkflowEnvironment) -> None:
    """No timer of its hour (the run's deadline has its own), and its row says so: `simulated`, its resolved duration
    as its input, its output `{}` as live."""
    store = MemoryStore()
    g = graph().node("d", DELAY, {"duration_s": 3600}).node("e", ECHO, {"value": 1}).edge("d", "e")
    async with workers(env.client, store):
        simulated = await start(env.client, store, g, {}, mode="simulate")
        await asyncio.wait_for(simulated.result(), RESULT_TIMEOUT_S)
        started = timers(await simulated.fetch_history())
    assert 3600 not in started
    [row] = [r for r in store.steps(run_id_of(simulated)) if r.node_key == "d"]
    assert (row.status, row.outcome, row.input_preview, row.output_preview) == (
        "succeeded", "simulated", {"duration_s": 3600}, {},
    )  # fmt: skip


async def test_a_simulated_delay_that_resolves_to_a_bad_value_fails_as_live(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("d", DELAY, {"duration_s": cel("0 - 5")})
    async with workers(env.client, store):
        results = []
        for mode in ("live", "simulate"):
            handle = await start(env.client, store, g, {}, mode=mode)
            results.append(await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S))
    (live, simulated) = results
    assert live.status == simulated.status == "failed"
    assert live.error and simulated.error and live.error["code"] == simulated.error["code"]


@dataclasses.dataclass
class Batches(MemoryStore):
    """Each projection's count of `not_started` rows: how a run's ends are spread."""

    unstarted: list[int] = dataclasses.field(default_factory=list)

    async def project(self, data: ProjectInput) -> None:
        self.unstarted.append(sum(1 for r in data.steps if r.status == "not_started"))
        await super().project(data)


async def test_a_run_that_ends_with_many_open_instances_rows_them_over_several_projections(
    own_env: WorkflowEnvironment,
) -> None:
    """A workflow task's CPU (engine 2b spec §5.3): ends are made into rows at most ENDS_PER_PROJECTION at a time, one
    projection each, never all in the activation that ended the run. `f` fails at once; of the 1,197 steps the loop
    opened beside it (3 iterations of 399: a graph holds 500 steps), the in-flight cap starts 100 or fewer, and the
    rest never start. On a test server of its own: the run ends while those activities run, and a shared server would
    stop skipping time."""
    store = Batches()
    g = graph().node("f", FAIL_N, {"failures": 10})
    g.nodes[0]["options"]["max_attempts"] = 1
    g.node("l", LOOP, {"items": [0, 1, 2], "concurrency": 3})
    for n in range(399):  # slow: a quick body beside the failure meets a known hang on main (its own task)
        g.node(f"e{n}", SLOW, {"seconds": 30}).edge("l", f"e{n}", "body")
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.status == "failed"
    rows = store.steps(run_id_of(handle))
    assert len({(r.node_key, r.iteration_key) for r in rows}) == 2 + 3 * 399  # every instance has its row
    unstarted = [n for n in store.unstarted if n]
    assert sum(unstarted) >= 1_000 and max(unstarted) <= 500 and len(unstarted) >= 3
    from dewpoint.engine.runtime.execution import ENDS_PER_PROJECTION

    assert ENDS_PER_PROJECTION == 500  # below what a projection's bytes allow (about 700 such rows): it's what cuts
