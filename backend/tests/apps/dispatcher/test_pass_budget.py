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
