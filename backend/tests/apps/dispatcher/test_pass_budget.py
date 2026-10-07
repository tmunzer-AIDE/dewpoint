# SPDX-License-Identifier: Apache-2.0
"""A leader pass's soft budget (the owner's D16 review of the 2b-4b M1 checkpoint 3: a prototype to test, not the
proposed guarantee): a pass always takes its first item; it takes no new one once it has run `PASS_S`, or once a
Temporal call made in it took longer than `SLOW_S`, ran out its deadline or found Temporal unavailable. An item it took
runs to its end, and the passes after it in the cycle still take theirs. Among the items a pass picked, it takes first
those it hasn't taken lately, so one slow item can't keep the others waiting. Counted in items and calls; timed only
where the budget itself is time."""

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import budget


class _Service:
    """A service client's one RPC path, as the SDK's: each call takes `delays[rpc]` seconds, or raises `fails[rpc]`."""

    def __init__(self) -> None:
        self.delays: dict[str, float] = {}
        self.fails: dict[str, RPCError] = {}
        self.calls: list[str] = []

    async def _rpc_call(self, rpc: str, req: Any, resp_type: Any, **kw: Any) -> str:
        self.calls.append(rpc)
        await asyncio.sleep(self.delays.get(rpc, 0))
        if rpc in self.fails:
            raise self.fails[rpc]
        return rpc


def _client() -> Any:
    client = SimpleNamespace(service_client=_Service())
    budget.instrument(client)  # type: ignore[arg-type]
    return client


async def _call(client: Any, rpc: str) -> Any:
    return await client.service_client._rpc_call(rpc, None, None, service="workflow", retry=False, metadata={},
                                                 timeout=None)  # fmt: skip


async def test_a_pass_takes_its_first_item_always_and_no_new_one_once_its_budget_is_spent(monkeypatch) -> None:
    """Counted on a clock of the test's own (the review of checkpoint 4: real time flaked under a loaded machine): each
    item takes 4 s of a 10-second budget, so the pass takes three; one that takes the whole budget is still taken."""
    now = [0.0]
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(budget, "PASS_S", 10.0)
    taken: list[int] = []
    with budget.passing("p") as admitted:
        for item in admitted(range(10), key=lambda i: i):
            taken.append(item)
            now[0] += 4.0
    assert taken == [0, 1, 2] and admitted.deferred == 7
    with budget.passing("first") as admitted:
        taken = []
        for item in admitted(range(3), key=lambda i: i):
            taken.append(item)
            now[0] += 11.0  # over the whole budget: the first is still taken, and only it
    assert taken == [0] and admitted.deferred == 2


@pytest.mark.parametrize("why", ["slow", "deadline", "unavailable"])
async def test_a_slow_call_ends_its_passs_admission_once_the_item_it_was_made_for_ends(monkeypatch, why) -> None:
    """A call over `SLOW_S`, or one Temporal answered DEADLINE_EXCEEDED or UNAVAILABLE: the item it was made for goes
    on to its end (its later calls are made), then the pass takes no new one."""
    monkeypatch.setattr(budget, "SLOW_S", 0.05)
    client = _client()
    if why == "slow":
        client.service_client.delays["describe_schedule"] = 0.08
    else:
        status = RPCStatusCode.DEADLINE_EXCEEDED if why == "deadline" else RPCStatusCode.UNAVAILABLE
        client.service_client.fails["describe_schedule"] = RPCError(why, status, b"")
    taken = []
    with budget.passing("p") as admitted:
        for item in admitted(range(5), key=lambda i: i):
            taken.append(item)
            try:
                await _call(client, "describe_schedule")
            except RPCError:
                pass
            await _call(client, "patch_schedule")  # the same item's later call
    assert taken == [0] and admitted.slow and admitted.deferred == 4
    assert client.service_client.calls == ["describe_schedule", "patch_schedule"]


async def test_a_call_outside_any_pass_marks_none_and_each_pass_starts_afresh(monkeypatch) -> None:
    """Calls the process makes outside a pass (the admission worker's) mark nothing; a pass marked slow leaves the next
    pass of the cycle its own budget: it takes its items."""
    monkeypatch.setattr(budget, "SLOW_S", 0.01)
    client = _client()
    client.service_client.delays["describe_schedule"] = 0.03
    await _call(client, "describe_schedule")
    with budget.passing("slow") as slow:
        for _ in slow(range(3), key=lambda i: i):
            await _call(client, "describe_schedule")
    client.service_client.delays.clear()
    with budget.passing("next") as after:
        taken = [i for i in after(range(3), key=lambda i: i)]
    assert slow.deferred == 2 and taken == [0, 1, 2] and not after.slow


async def test_a_pass_takes_first_the_items_it_hasnt_taken_lately(monkeypatch) -> None:
    """Fairness: a pass stopped after its first item (always slow, say) takes another first next time, then the one it
    has taken least lately; the items it no longer picks are forgotten."""
    monkeypatch.setattr(budget, "PASS_S", 0.0)  # one item a pass
    order = []
    for _ in range(4):
        with budget.passing("fair") as admitted:
            order += list(admitted(["a", "b", "c"], key=lambda i: i))
    assert order == ["a", "b", "c", "a"]
    with budget.passing("fair") as admitted:
        assert list(admitted(["d", "b"], key=lambda i: i)) == ["d"]
    assert set(budget._visits["fair"]) == {"d", "b"}


async def test_the_hook_times_every_call_once_however_often_it_is_installed() -> None:
    client = _client()
    budget.instrument(client)
    started = time.monotonic()
    assert await _call(client, "describe_namespace") == "describe_namespace"
    assert client.service_client.calls == ["describe_namespace"] and time.monotonic() - started < 1


async def test_a_pass_its_slow_calls_stopped_reports_its_degraded_state_and_alerts_once_a_while(monkeypatch) -> None:
    """The owner's review of checkpoint 4: a steadily slow Temporal leaves every pass one item a cycle, a degraded
    state that must be explicit, never taken for its five-minute accounting. A pass a slow call stopped reports it
    (`slow`), what it deferred, and whether its selection was full (`backlog`: more may wait beyond what it picked,
    which `deferred` doesn't count); and alerts (`dispatcher_pass_degraded`), at most every `DEGRADED_ALERT_S` a
    pass."""
    import structlog

    monkeypatch.setattr(budget, "SLOW_S", 0.01)
    monkeypatch.setattr(budget, "_alerted", {})
    client = _client()
    client.service_client.delays["describe_schedule"] = 0.03
    reports = []
    with structlog.testing.capture_logs() as logs:
        for _ in range(2):
            counts: dict[str, int] = {}
            with budget.passing("degraded") as admitted:
                for _item in admitted(range(4), key=lambda i: i):
                    await _call(client, "describe_schedule")
                admitted.reported(counts, full=True)
            reports.append(counts)
    assert reports == [{"deferred": 3, "slow": 1, "backlog": 1}] * 2
    alerts = [entry for entry in logs if entry["event"] == "dispatcher_pass_degraded"]
    assert len(alerts) == 1 and alerts[0]["pass_name"] == "degraded" and alerts[0]["log_level"] == "error"


def _runs(monkeypatch: Any, items_s: list[tuple[int, float]], gap_s: float) -> tuple[list[dict[str, int]], list[Any]]:
    """Runs of pass `p` on the test's clock, each picking `n` items of `s` seconds, `gap_s` apart; no call slow.
    Its reports and its alerts."""
    import structlog

    now = [0.0]
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(budget, "PASS_S", 10.0)
    monkeypatch.setattr(budget, "_alerted", {})
    monkeypatch.setattr(budget, "_limited", {})
    reports = []
    with structlog.testing.capture_logs() as logs:
        for n, seconds in items_s:
            counts: dict[str, int] = {}
            with budget.passing("p") as admitted:
                for _item in admitted(range(n), key=lambda i: i):
                    now[0] += seconds
                admitted.reported(counts, full=True)
            reports.append(counts)
            now[0] += gap_s
    return reports, [entry for entry in logs if entry["event"] == "dispatcher_pass_degraded"]


async def test_a_pass_its_budget_keeps_limiting_alerts_though_no_call_is_slow(monkeypatch) -> None:
    """The owner's review of checkpoint 5 (M8): calls just under `SLOW_S` (0.9 s measured) stopped each pass at its
    budget, a fifth of its items taken, every cycle, and nothing alerted: only a slow call did. A pass that defers items
    in every run for `SUSTAINED_S` alerts too (`why`: the budget), at most every `DEGRADED_ALERT_S`."""
    reports, alerts = _runs(monkeypatch, [(10, 4.0)] * 5, gap_s=28.0)  # each run 12 s, 3 of 10 taken; 40 s apart
    assert all(r == {"deferred": 7, "backlog": 1} for r in reports), reports
    assert len(alerts) == 1 and alerts[0]["why"] == "budget" and alerts[0]["log_level"] == "error"
    assert alerts[0]["deferred"] == 7  # at the third run's end: deferring since the first's, 80 s


async def test_neither_a_passing_deferral_nor_a_full_pick_alone_alerts(monkeypatch) -> None:
    """A run that defers, then one that takes all it picked, then one that defers: never a minute of it. And a pick
    that is full each time (more may wait) but takes all it picked, for ten minutes: degraded in nothing shown."""
    _, alerts = _runs(monkeypatch, [(10, 4.0), (2, 4.0), (10, 4.0), (2, 4.0), (10, 4.0)], gap_s=28.0)
    assert alerts == []
    _, alerts = _runs(monkeypatch, [(50, 0.01)] * 60, gap_s=10.0)
    assert alerts == []
